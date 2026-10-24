import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("verification", Path(__file__).with_name("verification.py"))
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class VerificationTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = self.root.resolve() / "candidate"
        self.repo.mkdir()
        self.enterContext(mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull}))
        before = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, before)
        self.git("init", "-q")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.com")
        (self.repo / "source.ts").write_text("base\n")
        (self.repo / ".gitignore").write_text("dist/\nnode_modules/\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.patch = self.root / "candidate.patch"
        self.patch.write_text("patch data")
        self.evidence = self.root / "evidence.json"
        v.freeze(self.base, self.patch, self.evidence)

    def git(self, *args):
        return subprocess.check_output(["git", *args], text=True)

    def test_detects_check_mutations_and_patch_replacement(self):
        for name in ("source.ts", "new.ts", ".gitignore"):
            with self.subTest(name=name):
                path = self.repo / name
                original = path.read_text() if path.exists() else None
                path.write_text("changed\n")
                with self.assertRaisesRegex(ValueError, "checked-source-changed"):
                    v.unchanged(self.base, self.patch, self.evidence)
                if original is None:
                    path.unlink()
                else:
                    path.write_text(original)
        self.patch.write_text("replaced")
        with self.assertRaisesRegex(ValueError, "checked-source-changed"):
            v.unchanged(self.base, self.patch, self.evidence)

    def test_checked_added_file_stays_attested_after_it_becomes_ignored(self):
        added = self.repo / "added.ts"
        added.write_text("checked\n")
        self.git("add", "--intent-to-add", "added.ts")
        (self.repo / ".gitignore").write_text("added.ts\n")
        v.freeze(self.base, self.patch, self.evidence)
        added.write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "checked-source-changed"):
            v.unchanged(self.base, self.patch, self.evidence)

    def test_ignores_generated_files_and_preserves_index(self):
        before = self.git("status", "--porcelain")
        (self.repo / "dist").mkdir()
        (self.repo / "dist/output.js").write_text("generated")
        v.unchanged(self.base, self.patch, self.evidence)
        self.assertEqual(self.git("status", "--porcelain"), before)

    def test_candidate_cannot_mount_controls_or_actions_command_files(self):
        cmd = v.command("test", self.repo)
        mounts = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--mount"]
        self.assertEqual(len(mounts), 2)
        self.assertIn(f"src={self.repo},dst=/workspace", mounts[0])
        self.assertIn("dst=/workspace/.git,readonly", mounts[1])
        self.assertNotIn("--privileged", cmd)
        self.assertNotIn("--env-file", cmd)
        self.assertNotIn("GITHUB_OUTPUT", str(cmd))
        self.assertEqual(cmd[-2:], ["pnpm", "test"])

    def test_successful_check_with_mutation_fails_before_next_stage(self):
        real_run = subprocess.run
        def mutate(args, **kwargs):
            if args[0] != "docker":
                return real_run(args, **kwargs)
            (self.repo / "source.ts").write_text("changed\n")
            return subprocess.CompletedProcess(args, 0)
        with mock.patch.object(v.subprocess, "run", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "checked-source-changed"):
                v.main(["lint", self.base, str(self.patch), str(self.evidence)])

    def test_infrastructure_failure_is_fatal_but_check_failure_is_repairable(self):
        marker = self.root / "verification-failed"
        real_run = subprocess.run
        for status, fatal in ((1, False), (125, True), (126, True), (127, True)):
            def run(args, **kwargs):
                if args[0] == "docker":
                    return subprocess.CompletedProcess(args, status)
                return real_run(args, **kwargs)
            with mock.patch.dict(os.environ, {"VERIFICATION_FAILURE": str(marker)}), \
                    mock.patch.object(v.subprocess, "run", side_effect=run):
                self.assertEqual(v.entry(["lint", self.base, str(self.patch), str(self.evidence)]), 1)
            self.assertEqual(marker.exists(), fatal)
            if fatal:
                with self.assertRaisesRegex(ValueError, "verification-failed"):
                    v.main(["assert", str(marker)])
            marker.unlink(missing_ok=True)

    def test_cli_isolated_imports_ignore_candidate_python_files(self):
        (self.repo / "json.py").write_text("raise RuntimeError('candidate import')")
        result = subprocess.run([sys.executable, "-I", v.__file__, "freeze", self.base,
                                 str(self.patch), str(self.evidence)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.evidence.read_text())["base"], self.base)
