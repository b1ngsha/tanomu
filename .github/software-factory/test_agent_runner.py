import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

RUNNER = Path(__file__).with_name("agent_runner.py").resolve()
spec = importlib.util.spec_from_file_location("agent_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class InvocationTest(unittest.TestCase):
    def test_shared_flags_and_explicit_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {"CLAUDE_CONFIG_DIR": str(root / "config"), "CLAUDE_TRANSCRIPT": "stale",
                   "CLAUDE_SETTINGS": "settings.json", "ANTHROPIC_MODEL": "configured-model"}
            for persisted in (False, True):
                with self.subTest(persisted=persisted), patch.dict(os.environ, env, clear=True), \
                        patch.object(runner.subprocess, "run") as run:
                    run.return_value.returncode = 0
                    status = runner.invoke("review-standards", "private prompt", 600, root / "result.json",
                                           root / "summary", schema="schema",
                                           session_file=root / "session" if persisted else None)
                    self.assertEqual(status, 0)
                    args = run.call_args.args[0]
                    self.assertEqual(args[:3], [sys.executable, "-I", str(RUNNER.with_name("supervisor.py"))])
                    self.assertEqual(args[3:8], [str(root / "result.json"), str(root / "summary"),
                                                "review-standards", "600", "--"])
                    command = args[8:]
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
                        self.assertEqual(run.call_args.kwargs["env"]["CLAUDE_TRANSCRIPT"],
                                         str(root / "config/projects/factory" / f"{session}.jsonl"))
                        self.assertNotIn("--no-session-persistence", command)
                    else:
                        self.assertIn("--no-session-persistence", command)
                        self.assertNotIn("--session-id", command)
                        self.assertNotIn("CLAUDE_TRANSCRIPT", run.call_args.kwargs["env"])

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
        with patch.dict(os.environ, {"CLAUDE_SETTINGS": "settings", "ANTHROPIC_MODEL": "model"}), \
                patch.object(runner.subprocess, "run", side_effect=OSError("private details")):
            self.assertEqual(runner.invoke("final-spec", "prompt", 1, "result", "summary"), 127)

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
            for mode, context in (("round", ["6"]), ("final", ["b" * 40, "a" * 40, "true"])):
                with self.subTest(mode=mode):
                    result = subprocess.run([sys.executable, "-I", str(script), mode, "2", "--", *context],
                                            env=env, cwd=root, capture_output=True, text=True, timeout=10)
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
                             "standards=started\nstandards=passed\nspec=started\nspec=passed\n" * 2)


if __name__ == "__main__":
    unittest.main()
