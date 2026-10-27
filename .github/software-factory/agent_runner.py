"""Trusted agent invocation and sequential review axes; workflow job IO stays in shell."""
import contextlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent


def trusted_module(name):
    # -I excludes the script directory; never import from the candidate cwd or PYTHONPATH.
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke(phase, prompt, budget, result, summary, *, schema=None,
           tools="Read,Glob,Grep", session_file=None, persist=False):
    """One supervised invocation. Persistence is explicit; all permission flags are shared."""
    command = ["claude", "-p", "--bare", "--restricted", "--output-format", "json"]
    env = dict(os.environ)
    env.pop("CLAUDE_TRANSCRIPT", None)
    if persist or session_file is not None:
        session = str(uuid.uuid4())
        if session_file is not None:
            Path(session_file).write_text(session)
        command += ["--session-id", session]
        env["CLAUDE_TRANSCRIPT"] = str(Path(env["CLAUDE_CONFIG_DIR"]) / "projects" / "factory" / f"{session}.jsonl")
    else:
        command += ["--no-session-persistence"]
    if schema is not None:
        command += ["--json-schema", schema]
    command += ["--tools", tools, "--permission-mode", "dontAsk", "--permission-prompts", "none",
                "--disable-slash-commands", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--settings", env["CLAUDE_SETTINGS"], "--model", env["ANTHROPIC_MODEL"], prompt]
    try:
        # Keep cancellation and cleanup in one process. An outer subprocess.run() can
        # kill the supervisor on KeyboardInterrupt before its TERM/KILL grace ends.
        supervisor = trusted_module("supervisor")
        previous = os.environ.get("CLAUDE_TRANSCRIPT")
        try:
            if "CLAUDE_TRANSCRIPT" in env:
                os.environ["CLAUDE_TRANSCRIPT"] = env["CLAUDE_TRANSCRIPT"]
            else:
                os.environ.pop("CLAUDE_TRANSCRIPT", None)
            return supervisor.main([str(result), str(summary), phase, str(budget), "--", *command])
        finally:
            if previous is None:
                os.environ.pop("CLAUDE_TRANSCRIPT", None)
            else:
                os.environ["CLAUDE_TRANSCRIPT"] = previous
    except OSError:
        return 127


def outcome(axis, state):
    # Both fields are trusted constants, never model text or provider errors.
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"{axis}={state}\n")


def error_marker(error):
    reason = str(error) if isinstance(error, ValueError) and re.fullmatch(r"[a-z-]+", str(error)) else "agent-runner-failed"
    print(f"::error::{reason}", file=sys.stderr)


def schema_json(control, mode):
    with contextlib.redirect_stdout(io.StringIO()) as schema:
        control.claude_schema(mode)
    return schema.getvalue().rstrip("\n")


def run_axis(control, axis, phase, prompt, budget, result, schema, mode, temp, verify=False):
    """A fresh supervised session per phase; invalid output fails before the next phase."""
    outcome(axis, "started")
    try:
        status = invoke(phase, prompt, budget, result, temp / f"{phase}-summary.txt",
                        schema=schema,
                        session_file=temp / f"{phase}.session" if mode == "round" else None)
    except Exception:
        status = 127
    if status:
        failure = "timeout" if status == 124 else "runner-error"
        outcome(axis, failure)
        print(f"::error::{axis}-{failure}")
        return status
    try:
        (control.claude_result if verify else control.claude_findings)(result)
    except Exception as error:
        outcome(axis, "invalid-output")
        error_marker(error)
        return 1
    outcome(axis, "passed")
    return 0


def single(mode, budget, prompt):
    control = trusted_module("control")
    canary = mode.startswith("canary-")
    writable = mode != "canary-final"
    name = "claude-canary" if canary else "implementation"
    temp = Path(os.environ["RUNNER_TEMP"])
    result = temp / f"{name}.json"
    status = invoke("implement" if writable else "final-standards", prompt, budget, result,
                    temp / f"{name}-summary.txt",
                    schema=schema_json(control, "round" if writable else "final") if canary else None,
                    tools="Read,Glob,Grep,Edit,Write,Bash" if writable else "Read,Glob,Grep",
                    session_file=None if canary else temp / "implementation.session", persist=writable)
    if status and not canary:
        print(f"::error::claude-exit-{status}")
    if not status and not canary:
        control.claude_result(result)
    return status


def review(mode, budget, *args):
    control = trusted_module("control")  # Lazy to allow control to reuse invoke later.
    prefix = "review" if mode == "round" else "final"
    axes = ("standards", "spec") if mode == "round" or args[-1] == "true" else ("standards",)
    if mode == "round":
        if args[-1] not in ("true", "false"):
            raise ValueError("invalid-agent-runner-input")
    context = args if mode == "round" else args[:2]
    schema = schema_json(control, mode)
    temp = Path(os.environ["RUNNER_TEMP"])
    files = []
    for axis in axes:
        phase = f"{prefix}-{axis}"
        result = temp / f"{phase}.json"
        try:
            prompt = control.prompt(phase, *context).rstrip("\n")
        except Exception as error:
            error_marker(error)
            return 1
        status = run_axis(control, axis, phase, prompt, budget, result, schema, mode, temp)
        if status:
            return status
        files.append((axis.title(), result))
    confirmed = None
    if mode == "round":
        claims = [{"axis": axis, **item} for axis, name in files
                  for item in control.claude_findings(name) if item["blocking"]]
        # Identical claims share one verification; their text is the report's deduplication key.
        claims = list({f"{item['axis']}: {item['finding']}": item for item in claims}.values())
        claims = [{"id": index, **item} for index, item in enumerate(claims)]
        claim_texts = [f"{item['axis']}: {item['finding']}" for item in claims]
        if not claims:
            outcome("verify", "skipped")
        else:
            # Findings reach the verifier as workspace data, never as interpolated prompt text.
            Path(".factory-input/blocking.json").write_text(json.dumps(claims))
            result = temp / "review-verify.json"
            status = run_axis(control, "verify", "review-verify", control.verify_prompt().rstrip("\n"),
                              budget, result, schema_json(control, "verify"), mode, temp, verify=True)
            if status:
                return status
            try:
                verdicts = control.claude_verdicts(result, claim_texts)
            except Exception as error:
                outcome("verify", "invalid-output")
                error_marker(error)
                return 1
            confirmed = {claim: verdicts[index] for index, claim in enumerate(claim_texts)}
    control.claude_review_result(files, os.environ["REVIEW_OUTPUT"], confirmed)
    control.scan(os.environ["REVIEW_OUTPUT"], limit=None)
    return 0


def install():
    version = trusted_module("control").CLAUDE_CODE_VERSION
    subprocess.run(["npm", "install", "--global", f"@anthropic-ai/claude-code@{version}",
                    "--no-audit", "--no-fund"], check=True)
    actual = subprocess.check_output(["claude", "--version"], text=True).strip()
    if actual != f"{version} (Claude Code)":
        raise ValueError("unexpected-claude-version")
    print(actual)
    return 0


def main(args):
    try:
        if args == ["install"]:
            return install()
        if args and args[0] == "canary":
            _, role, *args = args
            if role not in ("implement", "final"):
                raise ValueError("invalid-agent-runner-input")
            args = [f"canary-{role}", *args]
        mode, budget, separator, *context = args
        if (mode not in ("round", "final", "implement", "canary-implement", "canary-final") or separator != "--"
                or len(context) != (3 if mode == "final" else 2 if mode == "round" else 1)
                or mode == "final" and context[-1] not in ("true", "false")
                or not math.isfinite(float(budget)) or float(budget) <= 0):
            raise ValueError("invalid-agent-runner-input")
        if mode in ("round", "final"):
            return review(mode, budget, *context)
        return single(mode, budget, context[0])
    except Exception as error:
        error_marker(error)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
