import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

RUNNER = Path(__file__).with_name("agent_runner.py").resolve()
spec = importlib.util.spec_from_file_location("agent_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class InvocationTest(unittest.TestCase):
    def test_shared_flags_and_explicit_persistence(self):
        supervisor = runner.trusted_module("supervisor")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {"CLAUDE_CONFIG_DIR": str(root / "config"), "CLAUDE_TRANSCRIPT": "stale",
                   "CLAUDE_SETTINGS": "settings.json", "ANTHROPIC_MODEL": "configured-model"}
            for persisted in (False, True):
                with self.subTest(persisted=persisted), patch.dict(os.environ, env, clear=True), \
                        patch.object(runner, "trusted_module", return_value=supervisor), \
                        patch.object(supervisor, "main") as run:
                    transcripts = []
                    run.side_effect = lambda _: transcripts.append(os.environ.get("CLAUDE_TRANSCRIPT")) or 0
                    status = runner.invoke("review-standards", "private prompt", 600, root / "result.json",
                                           root / "summary", schema="schema",
                                           session_file=root / "session" if persisted else None)
                    self.assertEqual(status, 0)
                    args = run.call_args.args[0]
                    self.assertEqual(args[:5], [str(root / "result.json"), str(root / "summary"),
                                               "review-standards", "600", "--"])
                    self.assertEqual(os.environ["CLAUDE_TRANSCRIPT"], "stale")
                    command = args[5:]
                    self.assertEqual(command[:4], ["claude", "-p", "--bare", "--restricted"])
                    for flag, value in (("--json-schema", "schema"), ("--output-format", "json"),
                                        ("--tools", "Read,Glob,Grep"), ("--permission-mode", "dontAsk"),
                                        ("--permission-prompts", "none"), ("--mcp-config", '{"mcpServers":{}}'),
                                        ("--settings", "settings.json"), ("--model", "configured-model")):
                        self.assertEqual(command[command.index(flag) + 1], value)
                    self.assertIn("--disable-slash-commands", command)
                    self.assertIn("--strict-mcp-config", command)
                    self.assertEqual(command[-1], "private prompt")
                    if persisted:
                        session = (root / "session").read_text()
                        self.assertEqual(command[command.index("--session-id") + 1], session)
                        self.assertEqual(transcripts, [str(root / "config/projects/factory" / f"{session}.jsonl")])
                        self.assertNotIn("--no-session-persistence", command)
                    else:
                        self.assertIn("--no-session-persistence", command)
                        self.assertNotIn("--session-id", command)
                        self.assertEqual(transcripts, [None])

    def test_role_cli_preserves_paths_schema_and_sessions(self):
        control = runner.trusted_module("control")
        with patch.dict(os.environ, {"RUNNER_TEMP": "/tmp/factory"}), \
                patch.object(runner, "trusted_module", return_value=control), \
                patch.object(control, "claude_result") as validate, \
                patch.object(runner, "invoke", return_value=0) as invoke:
            for args, phase, name, writable, canary in (
                    (["implement"], "implement", "implementation", True, False),
                    (["canary", "implement"], "implement", "claude-canary", True, True),
                    (["canary", "final"], "final-standards", "claude-canary", False, True)):
                with self.subTest(args=args):
                    self.assertEqual(runner.main([*args, "120", "--", "prompt"]), 0)
                    self.assertEqual(invoke.call_args.args, (phase, "prompt", "120",
                                     Path(f"/tmp/factory/{name}.json"), Path(f"/tmp/factory/{name}-summary.txt")))
                    options = invoke.call_args.kwargs
                    self.assertEqual(options["persist"], writable)
                    self.assertEqual(options["session_file"], None if canary else Path("/tmp/factory/implementation.session"))
                    self.assertEqual(options["tools"], "Read,Glob,Grep,Edit,Write,Bash" if writable else "Read,Glob,Grep")
                    self.assertEqual(options["schema"], runner.schema_json(control, "round" if writable else "final")
                                     if canary else None)
            validate.assert_called_once_with(Path("/tmp/factory/implementation.json"))

    def test_install_uses_shared_pin_and_rejects_mismatched_binary(self):
        control = runner.trusted_module("control")
        with patch.object(runner.subprocess, "run") as run, \
                patch.object(runner.subprocess, "check_output") as version:
            version.return_value = f"{control.CLAUDE_CODE_VERSION} (Claude Code)\n"
            with patch("builtins.print"):
                self.assertEqual(runner.main(["install"]), 0)
            run.assert_called_once_with(["npm", "install", "--global",
                                         f"@anthropic-ai/claude-code@{control.CLAUDE_CODE_VERSION}",
                                         "--no-audit", "--no-fund"], check=True)
            version.return_value = "wrong-version-private-output"
            with patch("builtins.print") as output:
                self.assertEqual(runner.main(["install"]), 1)
            self.assertEqual(output.call_args.args, ("::error::unexpected-claude-version",))

    def test_supervisor_launch_errors_are_bounded_statuses(self):
        supervisor = runner.trusted_module("supervisor")
        with patch.dict(os.environ, {"CLAUDE_SETTINGS": "settings", "ANTHROPIC_MODEL": "model",
                                    "CLAUDE_TRANSCRIPT": "stale"}), \
                patch.object(runner, "trusted_module", return_value=supervisor), \
                patch.object(supervisor, "main", side_effect=OSError("private details")):
            self.assertEqual(runner.invoke("final-spec", "prompt", 1, "result", "summary"), 127)
            self.assertEqual(os.environ["CLAUDE_TRANSCRIPT"], "stale")

    def test_wrapper_cancellation_waits_for_supervisor_cleanup(self):
        for cancel, group in ((signal.SIGINT, True), (signal.SIGTERM, False)):
            with self.subTest(cancel=cancel), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                child_pid, terminating = root / "child.pid", root / "terminating"
                binary = root / "claude"
                binary.write_text(f"#!{sys.executable} -I\n"
                                  "import os, signal, time\nfrom pathlib import Path\n"
                                  f"signal.signal(signal.SIGTERM, lambda *_: Path({str(terminating)!r}).touch())\n"
                                  f"Path({str(child_pid)!r}).write_text(str(os.getpid()))\n"
                                  "time.sleep(60)\n")
                binary.chmod(0o755)
                env = {**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                       "RUNNER_TEMP": str(root), "CLAUDE_CONFIG_DIR": str(root / "config"),
                       "CLAUDE_SETTINGS": "settings.json", "ANTHROPIC_MODEL": "stub",
                       "GITHUB_STEP_SUMMARY": str(root / "github-summary")}
                process = subprocess.Popen([sys.executable, "-I", str(RUNNER), "implement", "45", "--", "prompt"],
                                           env=env, cwd=root, start_new_session=True,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                child = None
                try:
                    deadline = time.monotonic() + 5
                    while not child_pid.exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(child_pid.exists())
                    child = int(child_pid.read_text())
                    if group:
                        os.killpg(process.pid, cancel)
                    else:
                        process.send_signal(cancel)
                    # Another cancellation during the full production grace period must not abort cleanup.
                    deadline = time.monotonic() + 3
                    while not terminating.exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(terminating.exists(), "supervisor did not begin child cleanup")
                    self.assertIsNone(process.poll(), "wrapper exited before cleanup completed")
                    process.send_signal(cancel)
                    stdout, stderr = process.communicate(timeout=20)
                    state_query = subprocess.run(["ps", "-o", "stat=", "-p", str(child)],
                                                 capture_output=True, text=True)
                    self.assertIn(state_query.returncode, (0, 1), state_query.stderr)
                    state = state_query.stdout.strip()
                    self.assertTrue(not state or state.startswith("Z"), state)
                    self.assertEqual(process.returncode, 128 + cancel, stderr)
                    summary = (root / "implementation-summary.txt").read_text()
                    self.assertEqual(json.loads(summary.removeprefix("agent-summary "))["exit_status"], 128 + cancel)
                    self.assertIn(summary.strip(), stdout)
                    self.assertIn("### Factory Agent run", (root / "github-summary").read_text())
                    self.assertEqual(stderr, "")
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    if child is not None:
                        try:
                            os.killpg(child, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    process.communicate(timeout=5)

    def test_isolated_subprocess_from_external_candidate_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # A symlink entry point and planted modules must still resolve trusted siblings under -I.
            script = root / "entry.py"
            script.symlink_to(RUNNER)
            for name in ("control", "supervisor", "agent_runner", "json", "pathlib", "uuid"):
                (root / f"{name}.py").write_text('raise RuntimeError("CANDIDATE_MODULE_LOADED")\n')
            (root / "auth.json").write_text('{"key":"private-provider-key"}')
            (root / "report").mkdir()
            binary = root / "bin"
            binary.mkdir()
            claude = binary / "claude"
            claude.write_text('#!/bin/bash\n'
                              'printf "%s\\n" "$CLAUDE_TRANSCRIPT" >> "$RUNNER_TEMP/transcripts"\n'
                              'if [ -n "$CLAUDE_TRANSCRIPT" ]; then\n'
                              '  mkdir -p "${CLAUDE_TRANSCRIPT%/*}"\n'
                              '  printf "native transcript\\n" > "$CLAUDE_TRANSCRIPT"\n'
                              'fi\n'
                              'printf \'%s\' \'{"type":"result","subtype":"success","is_error":false,'
                              '"structured_output":{"findings":[]}}\'\n')
            claude.chmod(0o755)
            env = {**os.environ, "PYTHONPATH": str(root), "PATH": f"{binary}:{os.environ['PATH']}",
                   "CLAUDE_SETTINGS": "settings.json", "ANTHROPIC_MODEL": "configured-model",
                   "CLAUDE_CONFIG_DIR": str(root / "config"), "CLAUDE_TRANSCRIPT": "stale",
                   "RUNNER_TEMP": str(root), "FACTORY_AUTH_FILE": str(root / "auth.json"),
                   "GITHUB_OUTPUT": str(root / "output"), "REVIEW_OUTPUT": str(root / "report/review.json")}
            env.pop("FINAL_PATCH", None)
            env.pop("GITHUB_STEP_SUMMARY", None)
            for mode, context in (("round", ["6", "false"]), ("final", ["b" * 40, "a" * 40, "true", "false"])):
                with self.subTest(mode=mode):
                    entry = """import importlib.util, os, signal, sys
spec = importlib.util.spec_from_file_location('agent_runner', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
handler = lambda *_: None
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, handler)
status = module.main(sys.argv[2:])
assert all(signal.getsignal(sig) is handler for sig in (signal.SIGINT, signal.SIGTERM))
assert os.environ['CLAUDE_TRANSCRIPT'] == 'stale'
sys.exit(status)
"""
                    result = subprocess.run([sys.executable, "-I", "-c", entry, str(script), mode, "5", "--", *context],
                                            env=env, cwd=root, capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertNotIn("CANDIDATE_MODULE_LOADED", result.stdout + result.stderr)
                    self.assertEqual(json.loads((root / "report/review.json").read_text())["verdict"], "approve")
            transcripts = (root / "transcripts").read_text().splitlines()
            self.assertEqual(transcripts[2:], ["", ""])
            self.assertNotEqual(transcripts[0], transcripts[1])
            for axis, transcript in zip(("standards", "spec"), transcripts):
                session = (root / f"review-{axis}.session").read_text()
                self.assertEqual(Path(transcript), root / "config/projects/factory" / f"{session}.jsonl")
                self.assertEqual(Path(transcript).read_text(), "native transcript\n")
                self.assertFalse((root / f"final-{axis}.session").exists())
            self.assertEqual((root / "output").read_text(),
                             "standards=started\nstandards=passed\nspec=started\nspec=passed\n"
                             "verify=skipped\nstandards=started\nstandards=passed\n"
                             "spec=started\nspec=passed\n")


if __name__ == "__main__":
    unittest.main()
