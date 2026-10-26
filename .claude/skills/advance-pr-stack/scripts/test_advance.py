import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("advance", Path(__file__).with_name("advance.py"))
advance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(advance)

class AdvanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.remote = self.root / "remote.git"
        self.git("init", "--bare", str(self.remote), cwd=self.root)
        self.git("init", "-b", "main", str(self.repo), cwd=self.root)
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        self.commit("root", "root\n")
        self.git("checkout", "-b", "parent")
        self.commit("parent", "one\n")
        parent = self.commit("parent", "one\ntwo\n")
        self.git("checkout", "-b", "child")
        child = self.commit("child", "child\n")
        self.git("checkout", "-b", "grandchild")
        grandchild = self.commit("grandchild", "grandchild\n")
        self.git("checkout", "main")
        self.git("merge", "--squash", "parent")
        self.git("commit", "-m", "squashed parent")
        merged = self.git("rev-parse", "HEAD").strip()
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "origin", "main", "child", "grandchild")
        self.prs = [self.pr(1, "parent", "main", parent, "closed", merged),
                    self.pr(2, "child", "parent", child),
                    self.pr(3, "grandchild", "child", grandchild)]
        self.calls = []
        self.real_command = advance.command
        self.auth = True
        self.base_deleted = True

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout

    def commit(self, name, contents):
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text(contents)
        self.git("add", name)
        self.git("commit", "-m", name)
        return self.git("rev-parse", "HEAD").strip()

    def pr(self, number, head, base, sha, state="open", merged=None):
        return dict(number=number, state=state, merged=bool(merged), merge_commit_sha=merged,
                    head=dict(ref=head, sha=sha, repo=dict(full_name="owner/repo")),
                    base=dict(ref=base, repo=dict(full_name="owner/repo")))

    def command(self, *args, **kwargs):
        self.calls.append(args)
        if args[:3] == ("git", "remote", "get-url"):
            return "git@github.com:owner/repo.git\n"
        if args[:2] == ("gh", "auth"):
            if not self.auth:
                raise advance.Stop("gh authentication failed")
            return ""
        if args[:2] == ("gh", "api"):
            endpoint = args[2]
            route = urlsplit(endpoint)
            if route.path.endswith("/timeline"):
                events = [{"event": "base_ref_deleted", "created_at": "t1"}, {"event": "closed", "created_at": "t2"}]
                return json.dumps([events if self.base_deleted else events[-1:]])
            if route.path.endswith("/pulls"):
                query = parse_qs(route.query)
                result = self.prs
                for field in ("head", "base"):
                    if field in query:
                        ref = query[field][0].split(":")[-1]
                        result = [p for p in result if p[field]["ref"] == ref]
                return json.dumps([result])
            pr = next(p for p in self.prs if endpoint.endswith("/" + str(p["number"])))
            for arg in args:
                if arg == "state=open":
                    pr["state"] = "open"
                if arg == "base=main":
                    pr["base"]["ref"] = "main"
            return json.dumps(pr)
        return self.real_command(*args, **kwargs)

    def invoke(self, *flags):
        output = io.StringIO()
        previous = Path.cwd()
        os.chdir(self.repo)
        try:
            with patch.object(advance, "command", self.command), contextlib.redirect_stdout(output):
                result = advance.main(["2", *flags])
        finally:
            os.chdir(previous)
        return result, output.getvalue()

    def test_auth_failure_and_default_dry_run_do_not_write(self):
        before = self.git("show-ref")
        self.auth = False
        self.assertEqual(self.invoke()[0], 1)
        self.auth = True
        result, output = self.invoke()
        self.assertEqual(result, 0, output)
        self.assertIn("dry-run", output)
        self.assertEqual(self.git("show-ref"), before)
        self.assertFalse((self.repo / ".git/advance-pr-stack").exists())
        self.assertFalse(any(c[0] == "git" and c[1] in ("push", "fetch", "rebase", "update-ref") for c in self.calls))

    def test_advances_squash_stack_and_preserves_unrelated_main_change(self):
        self.git("tag", "-a", "do-not-publish", "-m", "local only", "child")
        self.commit("unrelated", "main only\n")
        self.git("push", "origin", "main")
        self.git("config", "push.followTags", "true")
        (self.repo / "untracked").write_text("preserve me")
        result, output = self.invoke("--apply")
        self.assertEqual(result, 0, output)
        main = self.git("rev-parse", "main").strip()
        for branch in ("child", "grandchild"):
            self.git("merge-base", "--is-ancestor", main, branch)
            self.assertEqual(self.git("rev-parse", branch).strip(), self.git("rev-parse", "refs/heads/" + branch, cwd=self.remote).strip())
        self.assertEqual((self.repo / "untracked").read_text(), "preserve me")
        self.assertEqual(self.prs[1]["base"]["ref"], "main")
        pushes = [c for c in self.calls if c[:2] == ("git", "push")]
        self.assertEqual(len(pushes), 1)
        self.assertIn("--atomic", pushes[0])
        self.assertEqual(sum(c.startswith("--force-with-lease=") for c in pushes[0]), 2)
        self.assertTrue(all("--no-follow-tags" in c for c in pushes))
        self.assertEqual(self.git("tag", "-l", cwd=self.remote), "")

    def test_closed_child_restores_deleted_base_before_reopen(self):
        self.prs[1]["state"] = "closed"
        result, output = self.invoke("--apply")
        self.assertEqual(result, 0, output)
        self.assertEqual(self.prs[1]["state"], "open")
        self.assertEqual(self.git("rev-parse", "parent", cwd=self.remote).strip(), self.prs[0]["head"]["sha"])
        writes = [c for c in self.calls if c[:2] == ("git", "push") or "PATCH" in c]
        self.assertIn("state=open", writes[1])
        self.assertIn("base=main", writes[2])

    def test_merged_target_multiple_children_and_unmerged_parent_stop(self):
        for case in ("merged", "multiple", "parent", "manual"):
            with self.subTest(case=case):
                original = json.loads(json.dumps(self.prs))
                if case == "merged":
                    self.prs[1]["merged"] = True
                elif case == "multiple":
                    self.prs.append(self.pr(4, "other", "child", self.prs[2]["head"]["sha"]))
                elif case == "manual":
                    self.prs[1]["state"] = "closed"
                    self.base_deleted = False
                else:
                    self.prs[0]["merged"] = False
                result, output = self.invoke("--apply")
                self.assertEqual(result, 1, output)
                self.assertFalse(any("PATCH" in c or c[:2] == ("git", "push") for c in self.calls))
                self.prs = original
                self.base_deleted = True

    def test_pr_change_before_first_write_stops_without_overwriting_it(self):
        original = self.command
        self.prs = self.prs[:2]
        def move_pr(*args, **kwargs):
            if args[:2] == ("git", "fetch"):
                self.prs[1]["base"]["ref"] = "another-base"
            return original(*args, **kwargs)
        with patch.object(self, "command", move_pr):
            result, output = self.invoke("--apply")
        self.assertEqual(result, 1, output)
        self.assertEqual(self.prs[1]["base"]["ref"], "another-base")
        self.assertFalse(any("PATCH" in c or c[:2] == ("git", "push") for c in self.calls))

    def test_over_limit_stops_but_generated_paths_are_excluded(self):
        self.git("checkout", "child")
        self.prs[1]["head"]["sha"] = self.commit("large", "line\n" * 601)
        self.prs = self.prs[:2]
        self.git("checkout", "main")
        self.assertEqual(self.invoke()[0], 1)
        self.git("checkout", "child")
        self.git("mv", "large", "pnpm-lock.yaml")
        self.git("commit", "-m", "generated")
        self.prs[1]["head"]["sha"] = self.commit("apps/server/drizzle/meta/snapshot.json", "line\n" * 800)
        self.git("checkout", "main")
        self.assertEqual(self.invoke()[0], 0)

    def test_diff_mismatch_retains_journal_without_pushing(self):
        old = self.git("rev-parse", "child").strip()
        real_diff = advance.Stack.diff
        calls = 0
        def changed_diff(stack, base, head):
            nonlocal calls
            calls += 1
            return real_diff(stack, base, head) + ("changed" if calls > 2 else "")
        with patch.object(advance.Stack, "diff", changed_diff):
            result, output = self.invoke("--apply")
        self.assertEqual(result, 1, output)
        self.assertEqual(self.git("rev-parse", "child").strip(), old)
        self.assertFalse(any(c[:2] == ("git", "push") for c in self.calls))
        journal = next((self.repo / ".git/advance-pr-stack").glob("*/journal.json"))
        self.assertEqual(json.loads(journal.read_text())["branches"][0]["old"], old)
        self.assertIn("retarget", output)

    def test_unchanged_branches_skip_rebase_and_push(self):
        self.git("update-ref", "refs/heads/main", self.prs[0]["head"]["sha"])
        self.git("checkout", "child")
        self.prs[0]["merge_commit_sha"] = self.prs[0]["head"]["sha"]
        self.git("checkout", "main")
        self.git("push", "--force", "origin", "main", "child", "grandchild")
        self.assertEqual(self.invoke("--apply")[0], 0)
        self.assertFalse(any(c[:2] == ("git", "push") or "rebase" in c for c in self.calls))

    def test_nonancestor_missing_commits_and_dirty_tree_stop(self):
        for case in ("nonancestor", "missing", "dirty", "checkedout"):
            with self.subTest(case=case):
                original = json.loads(json.dumps(self.prs))
                if case == "nonancestor":
                    self.prs[0]["head"]["sha"] = self.git("rev-parse", "main").strip()
                elif case == "missing":
                    self.prs[0]["head"]["sha"] = self.prs[1]["head"]["sha"]
                elif case == "dirty":
                    (self.repo / "root").write_text("dirty")
                else:
                    self.git("checkout", "child")
                result, output = self.invoke("--apply")
                self.assertEqual(result, 1, output)
                self.assertFalse(any("PATCH" in c or c[:2] == ("git", "push") for c in self.calls))
                self.prs = original
                (self.repo / "root").write_text("root\n")
                self.git("checkout", "main")

    def test_conflict_keeps_worktree_and_reports_retarget(self):
        self.git("checkout", "child")
        self.prs[1]["head"]["sha"] = self.commit("root", "child version\n")
        self.prs = self.prs[:2]
        self.git("checkout", "main")
        self.commit("root", "main version\n")
        self.git("push", "origin", "main", "child")
        result, output = self.invoke("--apply")
        self.assertEqual(result, 1, output)
        self.assertIn("retarget", output)
        self.assertFalse(any(c[:2] == ("git", "push") for c in self.calls))
        self.assertTrue(list((self.repo / ".git/advance-pr-stack").glob("*/worktree/root")))

    def test_atomic_lease_rejects_concurrent_remote_change(self):
        original = self.command
        expected = self.git("rev-parse", "main").strip()
        def race(*args, **kwargs):
            if args[:2] == ("git", "push") and any(a.startswith("--force-with-lease=") for a in args):
                self.git("update-ref", "refs/heads/child", expected, cwd=self.remote)
            return original(*args, **kwargs)
        with patch.object(self, "command", race):
            result, output = self.invoke("--apply")
        self.assertEqual(result, 1, output)
        self.assertIn("Uncertain writes", output)
        self.assertEqual(self.git("rev-parse", "grandchild").strip(), self.git("rev-parse", "grandchild", cwd=self.remote).strip())

if __name__ == "__main__":
    unittest.main()
