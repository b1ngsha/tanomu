"""Execute candidate checks without mounting trusted controls or Actions command files."""
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

IMAGE = "tanomu-factory-verify:local"
COMMANDS = {"install": ["install", "--frozen-lockfile", "--ignore-scripts"],
            **{name: [name] for name in ("format", "lint", "typecheck", "build:admin", "test")}}


def git(*args, env=None):
    return subprocess.check_output(["git", "-c", "core.fsmonitor=false", *args], env=env,
                                   stderr=subprocess.DEVNULL).decode().strip()


def tree(base):
    """Include tracked and nonignored new files; leave the candidate index untouched."""
    with tempfile.TemporaryDirectory() as temporary:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(temporary) / "index")}
        index = Path(git("rev-parse", "--git-path", "index"))
        if index.exists():
            shutil.copyfile(index, env["GIT_INDEX_FILE"])
        else:
            git("read-tree", base, env=env)
        git("add", "--all", env=env)
        return git("write-tree", env=env)


def identify(base, patch):
    return {"base": base, "patch_sha256": hashlib.sha256(Path(patch).read_bytes()).hexdigest(),
            "tree": tree(base)}


def freeze(base, patch, output):
    Path(output).write_text(json.dumps(identify(base, patch)))


def unchanged(base, patch, evidence):
    if identify(base, patch) != json.loads(Path(evidence).read_text()):
        raise ValueError("checked-source-changed")


def command(stage, workspace):
    if stage not in COMMANDS:
        raise ValueError("invalid-check")
    workspace = Path(workspace).resolve()
    return ["docker", "run", "--rm", "--network", "host", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "512",
            "--user", f"{os.getuid()}:{os.getgid()}", "--env", "HOME=/tmp",
            "--env", "CI=true", "--env", "TEST_DATABASE_URL=postgres://tanomu:tanomu@localhost:5432/tanomu",
            "--mount", f"type=bind,src={workspace},dst=/workspace",
            "--mount", f"type=bind,src={workspace / '.git'},dst=/workspace/.git,readonly",
            IMAGE, "pnpm", *COMMANDS[stage]]


def main(args):
    stage, *context = args
    if stage == "assert":
        if Path(context[0]).exists():
            raise ValueError("verification-failed")
        return 0
    if stage == "freeze":
        freeze(*context)
        return 0
    if len(context) != 3:
        raise ValueError("invalid-verification-input")
    base, patch, evidence = context
    status = subprocess.run(command(stage, Path.cwd())).returncode
    # Formatting intentionally changes source; freeze its result before the remaining checks.
    if stage not in ("install", "format"):
        unchanged(base, patch, evidence)
    if status in (125, 126, 127) or status < 0:
        raise ValueError("verification-failed")
    return status


def entry(args):
    try:
        return main(args)
    except Exception as error:
        if os.environ.get("VERIFICATION_FAILURE"):
            Path(os.environ["VERIFICATION_FAILURE"]).touch()
        reason = str(error) if isinstance(error, ValueError) and str(error) in {
            "checked-source-changed", "invalid-check", "invalid-verification-input"} else "verification-failed"
        print(f"::error::{reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(entry(sys.argv[1:]))
