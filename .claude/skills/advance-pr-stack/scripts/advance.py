"""Advance one linear PR stack after its parent merges. Python stdlib only."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import re
import subprocess
from urllib.parse import urlencode
class Stop(Exception):
    pass

def command(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="surrogateescape")
    if result.returncode:
        raise Stop(f"{args[0]} failed: {result.stderr.strip()}")
    return result.stdout

class Stack:
    def __init__(self):
        self.repo = ""
        self.journal = None
        self.state = {"branches": [], "actions": []}

    def record(self, **updates):
        self.state.update(updates)
        if self.journal:
            with self.journal.open("w") as stream:
                json.dump(self.state, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())

    def write(self, label, *args):
        self.state["actions"].append({"action": label, "status": "pending"})
        self.record()
        output = command(*args)
        self.state["actions"][-1]["status"] = "done"
        self.record()
        return output

    def git(self, *args, cwd=None):
        return command("git", *args, cwd=cwd).strip()

    def api(self, suffix, *args):
        return json.loads(command("gh", "api", f"repos/{self.repo}/pulls{suffix}",
                                  "--hostname", "github.com", *args))

    def search(self, **query):
        pages = self.api("?" + urlencode(dict(state="all", per_page=100, **query)),
                         "--paginate", "--slurp")
        if not isinstance(pages, list):
            raise Stop("Unexpected GitHub list response")
        return [item for page in pages for item in (page if isinstance(page, list) else [page])]

    def load(self, number):
        pr = self.api(f"/{number}")
        if not isinstance(pr, dict) or pr.get("state") not in ("open", "closed"):
            raise Stop("Unexpected GitHub PR response")
        for side in ("head", "base"):
            ref = pr[side]["ref"]
            if pr[side]["repo"]["full_name"].lower() != self.repo.lower():
                raise Stop("Only same-repository PRs are supported")
            self.git("check-ref-format", f"refs/heads/{ref}")
        if pr["head"]["ref"] == "main":
            raise Stop("A PR head cannot be main")
        return pr

    def base_deleted_closure(self, number):
        pages = json.loads(command("gh", "api", f"repos/{self.repo}/issues/{number}/timeline?per_page=100",
                                   "--hostname", "github.com", "--paginate", "--slurp"))
        if not isinstance(pages, list):
            raise Stop("Unexpected GitHub timeline response")
        events = [item for page in pages for item in page if isinstance(item, dict)
                  and item.get("event") in ("base_ref_deleted", "closed", "reopened")]
        return (len(events) >= 2 and events[-1]["event"] == "closed"
                and events[-2]["event"] == "base_ref_deleted")

    def merged(self, pr):
        return bool(pr.get("merged") or pr.get("merged_at"))

    def available(self, branches):
        checked = {line.removeprefix("branch refs/heads/")
                   for line in self.git("worktree", "list", "--porcelain").splitlines()
                   if line.startswith("branch refs/heads/")}
        if checked.intersection(branches):
            raise Stop("Stack branches must not be checked out in any worktree")

    def plan(self, number):
        command("gh", "auth", "status", "--hostname", "github.com")
        if self.git("status", "--porcelain", "--untracked-files=no"):
            raise Stop("Tracked working tree and index must be clean")
        origins = [self.git("remote", "get-url", *flags, "origin") for flags in (("--all",), ("--push", "--all"))]
        for origin in origins:
            match = re.fullmatch(r"(?:git@github\.com:|https://github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?", origin)
            if not match or (self.repo and self.repo != match[1]):
                raise Stop("Origin must be one matching GitHub fetch/push repository")
            self.repo = match[1]
        target = self.load(number)
        if self.merged(target):
            raise Stop("Target PR is already merged")
        candidates = self.search(head=self.repo.split("/")[0] + ":" + target["base"]["ref"])
        if len(candidates) != 1:
            raise Stop("Expected exactly one parent PR")
        parent = self.load(candidates[0]["number"])
        if parent["base"]["ref"] != "main":
            raise Stop("Merged parent must target main")
        if not self.merged(parent):
            raise Stop("Parent PR must be merged")
        chain, seen = [], {parent["head"]["ref"]}
        while target:
            expected_base = chain[-1]["head"]["ref"] if chain else parent["head"]["ref"]
            if target["base"]["ref"] != expected_base:
                raise Stop("PR base left the linear stack")
            branch = target["head"]["ref"]
            if branch in seen or self.merged(target):
                raise Stop("Expected an unmerged linear chain")
            seen.add(branch)
            if self.git("rev-parse", "--verify", f"refs/heads/{branch}") != target["head"]["sha"]:
                raise Stop(f"Local branch differs from PR head: {branch}")
            if target["state"] == "closed" and chain:
                raise Stop("Only the direct child can be reopened")
            chain.append(target)
            children = self.search(base=branch)
            if len(children) > 1:
                raise Stop(f"Multiple child candidates for {branch}")
            target = self.load(children[0]["number"]) if children else None
        self.available(p["head"]["ref"] for p in chain)
        return parent, chain

    def diff(self, base, head):
        return command("git", "diff", "--binary", "--full-index", "--no-ext-diff",
                       "--no-textconv", "--no-renames", "--src-prefix=a/", "--dst-prefix=b/",
                       "--no-color", f"{base}...{head}", "--")

    def size(self, base, head):
        stats = self.git("diff", "--numstat", "-z", f"{base}...{head}", "--", ".",
                         ":(exclude)pnpm-lock.yaml", ":(exclude)apps/server/drizzle/meta/**")
        total = 0
        entries = iter(stats.split("\0"))
        for entry in entries:
            if not entry:
                continue
            added, deleted, name = entry.split("\t", 2)
            total += sum(int(n) for n in (added, deleted) if n != "-")
            if not name:  # Rename paths follow as two NUL-separated entries.
                next(entries)
                next(entries)
        if total > 600:
            raise Stop(f"PR exceeds 600 changed lines: {total}")

    def snapshot(self, parent, chain):
        base = parent["head"]["sha"]
        rows = []
        for pr in chain:
            head = pr["head"]["sha"]
            self.git("merge-base", "--is-ancestor", base, head)
            if base == head:
                raise Stop(f"Missing commits in {pr['head']['ref']}")
            if self.git("rev-list", "--merges", f"{base}..{head}"):
                raise Stop("Only linear commit chains are supported")
            self.size(base, head)
            rows.append(dict(branch=pr["head"]["ref"], pr=pr["number"], old=head, old_base=base, patch=self.diff(base, head)))
            base = head
        return rows

    def failure(self):
        observations = []
        for row in self.state["branches"]:
            branch = row["branch"]
            try:
                local = self.git("rev-parse", f"refs/heads/{branch}")
                remote = self.git("ls-remote", "--heads", "origin", f"refs/heads/{branch}")
                remote = remote.split()[0] if remote else "missing"
                observations.append(dict(branch=branch, local=local, remote=remote))
                print(f"Branch {branch}: local changed={local != row['old']}, remote changed={remote != row['old']} ({local}, {remote})")
            except (Stop, OSError) as error:
                print(f"Branch {branch}: unable to verify: {error}")
        self.record(observations=observations)

    def advance(self, parent, chain, rows):
        directory = Path(self.git("rev-parse", "--git-path", "advance-pr-stack")).resolve()
        directory.mkdir(exist_ok=True)
        run = Path(tempfile.mkdtemp(prefix="run-", dir=directory))
        self.journal = run / "journal.json"
        self.record(repo=self.repo, branches=[{k: v for k, v in r.items() if k != "patch"} for r in rows], parent=parent)
        self.git("fetch", "--no-tags", "origin", "refs/heads/main")
        new_base = self.git("rev-parse", "FETCH_HEAD")
        merged = parent.get("merge_commit_sha")
        if not merged:
            raise Stop("Merged parent has no merge commit")
        self.git("merge-base", "--is-ancestor", merged, new_base)
        self.record(main=new_base)
        for index, row in enumerate(rows):
            self.git("fetch", "--no-tags", "origin", f"refs/heads/{row['branch']}")
            row["lease"] = self.git("rev-parse", "FETCH_HEAD")
            self.state["branches"][index]["lease"] = row["lease"]
            self.record()
            if row["lease"] != row["old"]:
                raise Stop(f"Remote moved: {row['branch']}")
        first = chain[0]
        current = self.load(first["number"])
        if (self.merged(current) or current["state"] != first["state"]
                or current["base"]["ref"] != first["base"]["ref"]
                or current["head"]["sha"] != first["head"]["sha"]):
            raise Stop("Direct child moved before publication")
        if first["state"] == "closed":
            if not self.base_deleted_closure(first["number"]):
                raise Stop("Closed child was not closed by base deletion")
            branch = parent["head"]["ref"]
            remote = self.git("ls-remote", "--heads", "origin", f"refs/heads/{branch}")
            if remote and remote.split()[0] != parent["head"]["sha"]:
                raise Stop("Parent branch moved since merge")
            if not remote:
                self.write(f"recreate {branch}", "git", "push", "--atomic", "--no-follow-tags",
                           f"--force-with-lease=refs/heads/{branch}:", "origin",
                           f"{parent['head']['sha']}:refs/heads/{branch}")
            reopened = json.loads(self.write(f"reopen #{first['number']}", "gh", "api",
                       f"repos/{self.repo}/pulls/{first['number']}", "--hostname", "github.com",
                       "--method", "PATCH", "-f", "state=open"))
            if reopened.get("state") != "open":
                raise Stop("GitHub did not reopen the direct child")
        retargeted = json.loads(self.write(f"retarget #{first['number']} to main", "gh", "api",
                   f"repos/{self.repo}/pulls/{first['number']}", "--hostname", "github.com",
                   "--method", "PATCH", "-f", "base=main"))
        if retargeted.get("base", {}).get("ref") != "main":
            raise Stop("GitHub did not retarget the direct child")
        work = run / "worktree"
        self.git("worktree", "add", "--detach", str(work), new_base)
        for index, row in enumerate(rows):
            if self.git("merge-base", new_base, row["old"]) == new_base:
                head = row["old"]
            else:
                self.record(replay=dict(branch=row["branch"], onto=new_base, old_base=row["old_base"]))
                self.git("checkout", "--detach", row["old"], cwd=work)
                self.git("-c", "core.hooksPath=/dev/null", "-c", "rerere.enabled=false",
                         "rebase", "--no-autostash", "--no-update-refs", "--reapply-cherry-picks",
                         "--empty=stop", "--onto", new_base, row["old_base"], cwd=work)
                head = self.git("rev-parse", "HEAD", cwd=work)
            if self.diff(new_base, head) != row["patch"]:
                raise Stop(f"PR diff changed: {row['branch']}")
            self.size(new_base, head)
            row["new"] = head
            self.state["branches"][index].update(new=head, lease=row["lease"])
            self.record()
            new_base = head
        remote = {ref: sha for sha, ref in (line.split() for line in self.git("ls-remote", "--heads", "origin").splitlines())}
        expected = {"refs/heads/main": self.state["main"], **{f"refs/heads/{r['branch']}": r["lease"] for r in rows}}
        if any(remote.get(ref) != sha for ref, sha in expected.items()):
            raise Stop("Remote main or stack head moved before publication")
        self.available(r["branch"] for r in rows)
        for index, (pr, row) in enumerate(zip(chain, rows)):
            current = self.load(pr["number"])
            expected_base = "main" if index == 0 else chain[index - 1]["head"]["ref"]
            if (self.merged(current) or current["state"] != "open"
                    or current["head"]["sha"] != row["old"]
                    or current["base"]["ref"] != expected_base
                    or self.git("rev-parse", f"refs/heads/{row['branch']}") != row["old"]):
                raise Stop(f"PR or local branch moved: {row['branch']}")
        changed = [row for row in rows if row["new"] != row["old"]]
        if changed:
            self.write("atomic push: " + ", ".join(r["branch"] for r in changed), "git", "push",
                       "--atomic", "--no-follow-tags", *[f"--force-with-lease=refs/heads/{r['branch']}:{r['lease']}"
                                     for r in changed], "origin",
                       *[f"{r['new']}:refs/heads/{r['branch']}" for r in changed])
        self.available(r["branch"] for r in rows)
        for row in changed:
            self.write(f"local {row['branch']}", "git", "update-ref",
                       f"refs/heads/{row['branch']}", row["new"], row["old"])
        self.record(complete=True)
        print("Advanced: " + (", ".join(r["branch"] for r in changed) or "branches unchanged"))
        print(f"Journal and retained worktree: {run}")

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("direct_child_pr", type=int)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    stack = Stack()
    try:
        parent, chain = stack.plan(args.direct_child_pr)
        rows = stack.snapshot(parent, chain)
        if args.apply:
            stack.advance(parent, chain, rows)
            return 0
        print("dry-run: fetch main and heads; merged parent #" + str(parent["number"]))
        print(f"#{chain[0]['number']}: reopen if closed, retarget to main, verify diffs, atomic push")
        for pr in chain:
            print(f"#{pr['number']} {pr['head']['ref']}: advance after {pr['base']['ref']}")
        return 0
    except (Stop, KeyError, TypeError, ValueError, OSError) as error:
        print(f"Stopped: {error}")
        if stack.journal:
            stack.record(error=str(error))
            stack.failure()
            print(f"Recovery journal: {stack.journal}")
            print("Completed writes: " + ("; ".join(a["action"] for a in stack.state["actions"]
                                                      if a["status"] == "done") or "none"))
            print("Uncertain writes (inspect before retry): " +
                  ("; ".join(a["action"] for a in stack.state["actions"]
                             if a["status"] == "pending") or "none"))
        else:
            print("Completed writes: none")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
