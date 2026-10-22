"""Trusted factory gates. Run from the dispatch revision, never the candidate tree."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
MODEL = "opencode/deepseek-v4.1-flash-free"
MAX_ARTIFACT_BYTES = 512_000
# Credential-shaped tokens; the lookbehind keeps kebab-case text such as "task-..." from matching.
CREDENTIAL_PATTERN = re.compile(
    rb"(?<![A-Za-z0-9_-])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})"
    rb"|-----BEGIN [A-Z ]*PRIVATE KEY-----")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def git(*args, env=None):
    # The candidate controls the worktree, so never let it run fsmonitor hooks in a trusted gate.
    return subprocess.check_output(["git", "-c", "core.fsmonitor=false", *args], env=env)


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", path]))


def task(number):
    require(re.fullmatch(r"[1-9][0-9]*", number), "invalid-issue")
    value = json.loads((ROOT / "tasks" / f"{number}.json").read_text())
    require(value["issue"] == int(number), "invalid-task")
    return value


def gate(number, directory):
    spec = task(number)
    require(os.environ["GITHUB_REF"] == "refs/heads/main", "wrong-ref")
    require(os.environ["MODEL"] == MODEL, "unsupported-model")
    repo = os.environ["GITHUB_REPOSITORY"]
    owner = repo.split("/")[0]
    require(os.environ["GITHUB_ACTOR"] == owner, "wrong-actor")
    require(os.environ["GITHUB_TRIGGERING_ACTOR"] == owner, "wrong-triggering-actor")
    issue = api(f"repos/{repo}/issues/{number}")
    require("pull_request" not in issue and issue["state"] == "open", "not-open-issue")
    require(issue["user"]["login"] == owner, "wrong-author")
    labels = {label["name"] for label in issue["labels"]}
    require({"ready-for-agent", "agent:implement"} <= labels, "missing-authorization")
    require(not {"implementing", "needs-human", "ready-for-human"} & labels, "already-claimed")
    events = json.loads(subprocess.check_output([
        "gh", "api", "--paginate", "--slurp", f"repos/{repo}/issues/{number}/events?per_page=100"
    ]))
    authorizations = [event for page in events for event in page
                      if event.get("event") in ("labeled", "unlabeled")
                      and event.get("label", {}).get("name") == "agent:implement"]
    require(bool(authorizations) and authorizations[-1]["event"] == "labeled"
            and authorizations[-1]["actor"]["login"] == owner, "wrong-label-actor")
    body = issue.get("body") or ""
    require(hashlib.sha256(body.encode()).hexdigest() == spec["body_sha256"], "body-changed")
    for dependency in spec["blocked_by"]:
        blocker = api(f"repos/{repo}/issues/{dependency}")
        require(blocker["state"] == "closed" and blocker.get("state_reason") == "completed",
                "open-dependency")
    refs = api(f"repos/{repo}/git/matching-refs/heads/{spec['branch']}")
    require(not any(ref["ref"] == f"refs/heads/{spec['branch']}" for ref in refs), "branch-exists")
    pulls = api(f"repos/{repo}/pulls?state=all&head={owner}:{spec['branch']}")
    require(not pulls, "pr-exists")
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    (output / "issue.md").write_text(body)


def scope(number, base):
    spec = task(number)
    resolved = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "--end-of-options",
                               f"{base}^{{commit}}"], capture_output=True)
    require(resolved.returncode == 0, "invalid-base")
    base = resolved.stdout.decode().strip()
    # Stage the whole worktree, including untracked files, into a throwaway index so the
    # checks see exactly what `git add --all` would publish without touching the real index.
    with tempfile.TemporaryDirectory() as temporary:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(temporary) / "index")}
        index = Path(git("rev-parse", "--git-path", "index").decode().strip())
        if index.exists():
            shutil.copyfile(index, env["GIT_INDEX_FILE"])
        git("add", "--all", env=env)
        diff = ("diff", "--cached", "--no-renames", "--no-ext-diff", "--no-textconv")
        fields = git(*diff, "-z", "--raw", "--no-abbrev", base, env=env).split(b"\0")[:-1]
        require(bool(fields), "empty-patch")
        for metadata, path in zip(fields[::2], fields[1::2]):
            old_mode, new_mode, _, _, status = metadata.decode().split()
            require(os.fsdecode(path) in spec["allowed_paths"], "path-outside-allowlist")
            require(old_mode in (":100644", ":000000") and new_mode == "100644"
                    and status in ("A", "M"), "invalid-file-type")
        total = 0
        for line in git(*diff, "-z", "--numstat", base, env=env).split(b"\0")[:-1]:
            added, removed, _ = line.split(b"\t", 2)
            require(added.isdigit() and removed.isdigit(), "binary-patch")
            total += int(added) + int(removed)
        require(total <= spec["max_changed_lines"], "patch-too-large")
        check = subprocess.run(["git", "-c", "core.fsmonitor=false", *diff, "--check", base],
                               env=env, capture_output=True)
        require(check.returncode == 0, "whitespace-error")


def scan(filename):
    require(Path(filename).stat().st_size <= MAX_ARTIFACT_BYTES, "artifact-too-large")
    data = Path(filename).read_bytes()
    require(len(data) <= MAX_ARTIFACT_BYTES, "artifact-too-large")
    auth_path = os.environ.get("FACTORY_AUTH_FILE")
    if auth_path:
        def values(value):
            if isinstance(value, dict):
                for item in value.values():
                    yield from values(item)
            elif isinstance(value, list):
                for item in value:
                    yield from values(item)
            elif isinstance(value, str) and len(value) >= 8:
                # JSON event artifacts carry the escaped form, patches the raw one.
                yield value.encode()
                yield json.dumps(value)[1:-1].encode()
        require(not any(value in data for value in values(json.loads(Path(auth_path).read_text()))),
                "credential-in-artifact")
    require(not CREDENTIAL_PATTERN.search(data), "credential-pattern-in-artifact")


def review(filename):
    events = [json.loads(line) for line in Path(filename).read_text().splitlines()]
    require(events and all(isinstance(event, dict) and event.get("type") != "error"
                           and not event.get("error") for event in events), "invalid-events")
    text = "".join(event.get("part", {}).get("text", "") for event in events
                   if event.get("type") == "text")
    def unique(pairs):
        keys = [key for key, _ in pairs]
        require(len(keys) == len(set(keys)), "invalid-review")
        return dict(pairs)
    try:
        result = json.loads(text, object_pairs_hook=unique)
    except json.JSONDecodeError:
        raise ValueError("invalid-review") from None
    require(isinstance(result, dict) and set(result) == {"verdict", "findings"}, "invalid-review")
    require(result["verdict"] in ("approve", "request_changes"), "invalid-verdict")
    require(isinstance(result["findings"], list) and len(result["findings"]) <= 20
            and all(isinstance(item, str) and item.strip() and len(item) <= 2000
                    for item in result["findings"]),
            "invalid-findings")
    require((result["verdict"] == "approve") == (not result["findings"]), "inconsistent-review")
    return result


def configure(directory, mode):
    output = Path(directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name in ("data/opencode", "config", "cache", "state"):
        (output / name).mkdir(parents=True, exist_ok=True)
    permissions = {"*": "deny", "read": "allow", "glob": "allow", "grep": "allow", "list": "allow",
                   "edit": "deny", "external_directory": "deny", "bash": "deny", "webfetch": "deny",
                   "websearch": "deny", "task": "deny", "skill": "deny"}
    if mode == "implement":
        # Edits are limited to the task's files so the model cannot touch .git config or hooks
        # that later trusted git commands would execute. OpenCode matches workspace-relative
        # paths and the last matching rule wins, so the "*" deny must come first.
        workspace = Path(os.environ["FACTORY_WORKSPACE"]).resolve()
        edit = {"*": "deny"}
        for name in task(os.environ["FACTORY_ISSUE"])["allowed_paths"]:
            path = (workspace / name).resolve()
            require(re.fullmatch(r"[A-Za-z0-9._/-]+", name) and path.is_relative_to(workspace)
                    and ".git" not in Path(name).parts, "invalid-allowed-path")
            edit[path.relative_to(workspace).as_posix()] = "allow"
        permissions["edit"] = edit
    else:
        require(mode == "review", "invalid-mode")
    auth = output / "data/opencode/auth.json"
    auth.touch(mode=0o600)
    auth.chmod(0o600)
    auth.write_text(os.environ["OPENCODE_AUTH_JSON"])
    config = output / "opencode.json"
    config.write_text(json.dumps({"share": False, "permission": permissions}))
    with open(os.environ["GITHUB_ENV"], "a") as env:
        for key, value in {
            "XDG_DATA_HOME": output / "data", "XDG_CONFIG_HOME": output / "config",
            "XDG_CACHE_HOME": output / "cache", "XDG_STATE_HOME": output / "state",
            "OPENCODE_CONFIG": config, "FACTORY_AUTH_FILE": auth,
        }.items():
            env.write(f"{key}={value}\n")


if __name__ == "__main__":
    try:
        command, *args = sys.argv[1:]
        if command == "gate":
            gate(*args)
        elif command == "scope":
            scope(*args)
        elif command == "scan":
            scan(*args)
        elif command == "configure":
            configure(*args)
        elif command == "review":
            result = review(*args)
            Path(os.environ["REVIEW_OUTPUT"]).write_text(json.dumps(result))
            print(result["verdict"])
        else:
            raise ValueError("unknown-command")
    except Exception as error:
        # Never print subprocess output, model text, or credential values.
        reason = str(error) if isinstance(error, ValueError) and re.fullmatch(r"[a-z-]+", str(error)) else "control-failed"
        print(f"::error::{reason}", file=sys.stderr)
        sys.exit(1)
