import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import control  # noqa: E402
from test_final_review import BASE, BOT, HEAD, OTHER  # noqa: E402
from test_control import REPO, SECRET  # noqa: E402


class FinalRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source, self.input, self.output = (self.root / name for name in ("source", "input", "output"))
        self.source.mkdir()
        self.input.mkdir()
        self.enterContext(mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": "200"}))
        os.environ.pop("FACTORY_AUTH_FILE", None)
        self.identity = {"pr": 2, "head": HEAD, "base": BASE, "issues": [1], "run": "100"}
        self.files = {"identity.json": json.dumps(self.identity),
                      "review.json": json.dumps({"verdict": "approve", "findings": [],
                                                 "advisory": ["Standards: " + "Unicode é検 " * 20_000]})}
        self.current = {**self.identity, "base": OTHER, "issues": [], "run": "200"}
        (self.input / "identity.json").write_text(json.dumps(self.current))
        for name, value in self.files.items():
            (self.source / name).write_text(value)
        current = self.root / "current.json"
        current.write_text(json.dumps({"pr": 2, "head": HEAD, "eligible": True, "posted": []}))
        control.final_comments(self.source, self.source / "identity.json", current, self.root / "comments")
        self.bodies = [path.read_text() for path in sorted((self.root / "comments").glob("*.md"))]
        self.comments = [{"user": BOT, "body": self.bodies[0]}]
        self.record = {"id": 100, "workflow_id": 9, "path": ".github/workflows/final-review.yml",
                       "head_branch": "main", "event": "pull_request_target",
                       "repository": {"full_name": REPO}, "head_repository": {"full_name": REPO}}
        self.artifact = {"id": 55, "name": "final-review", "expired": False}
        self.extra = []
        self.archive_error = None
        self.api_calls, self.cli_calls = [], []

    def api(self, path):
        self.api_calls.append(path)
        if path.endswith("/actions/runs/100"):
            return self.record
        if path.endswith("/actions/workflows/final-review.yml"):
            return {"id": 9}
        if path.endswith("/reviews?per_page=100"):
            return []
        if path.endswith("/artifacts?name=final-review&per_page=100"):
            return {"artifacts": [self.artifact]}
        raise AssertionError(path)

    def cli(self, args, **kwargs):
        self.cli_calls.append(args)
        if args[2:4] == ["--paginate", "--slurp"]:
            return json.dumps([[], self.comments]).encode()
        if self.archive_error:
            raise self.archive_error
        self.assertEqual(args, ["gh", "api", f"repos/{REPO}/actions/artifacts/55/zip"])
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, text in self.files.items():
                archive.writestr(name, text)
            for info, text in self.extra:
                archive.writestr(info, text)
        return buffer.getvalue()

    def resume(self, event="pull_request_target"):
        with mock.patch.object(control, "api", side_effect=self.api), \
                mock.patch.object(control.subprocess, "check_output", side_effect=self.cli):
            return control.final_resume("2", event, self.input, self.output)

    def test_recovers_original_report_and_identity_without_executing_candidate(self):
        self.assertTrue(self.resume())
        self.assertEqual(json.loads((self.input / "identity.json").read_text()), self.identity)
        self.assertEqual({path.name: path.read_text() for path in self.output.iterdir()}, self.files)
        current = self.root / "publish.json"
        marker = control.FINAL_MARKER.fullmatch(self.bodies[0].split("\n", 1)[0])
        current.write_text(json.dumps({"pr": 2, "head": HEAD, "eligible": True,
                                      "posted": [[HEAD, marker[2], 1, len(self.bodies)]]}))
        control.final_comments(self.output, self.output / "identity.json", current, self.root / "remaining")
        self.assertEqual([path.read_text() for path in sorted((self.root / "remaining").glob("*.md"))],
                         self.bodies[1:])
        self.assertIn(f"repos/{REPO}/actions/runs/100", self.api_calls)

    def test_manual_dispatch_never_reuses_reports(self):
        self.assertFalse(self.resume("workflow_dispatch"))
        self.assertEqual((self.cli_calls, self.api_calls), ([], []))
        result = subprocess.run([sys.executable, "-I", control.__file__, "final-resume", "2",
                                 "workflow_dispatch", "unused", "unused"], capture_output=True, text=True, env={})
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "resumed=false\n", ""))

    def test_ignores_forged_complete_malformed_and_wrong_head_markers(self):
        for comments in (
            [{"user": {"login": "mallory", "type": "User"}, "body": self.bodies[0]}],
            [{"user": BOT, "body": "quoted " + self.bodies[0]}],
            [{"user": BOT, "body": body} for body in self.bodies],
            [{"user": BOT, "body": self.bodies[0].replace(HEAD, OTHER)}],
            [{"user": BOT, "body": self.bodies[0].replace("/actions/runs/100", "/actions/runs/200")}],
            [{"user": BOT, "body": self.bodies[0].replace(f"part=1/{len(self.bodies)}", "part=9/2")}],
        ):
            with self.subTest(comments=len(comments)):
                self.comments = comments
                self.assertFalse(self.resume())
                self.assertFalse(self.output.exists())

    def test_requires_trusted_workflow_origin(self):
        for field, value in (("workflow_id", 10), ("path", ".github/workflows/evil.yml"),
                             ("head_branch", "pr-branch"), ("event", "pull_request"),
                             ("repository", {"full_name": "other/repo"}),
                             ("head_repository", {"full_name": "other/repo"})):
            with self.subTest(field=field), mock.patch.dict(self.record, {field: value}):
                self.assertFalse(self.resume())
                self.assertFalse(self.output.exists())
        self.record["event"] = "workflow_dispatch"
        self.assertTrue(self.resume())

    def test_missing_expired_and_invalid_archive_fall_back_to_fresh_review(self):
        for error in (subprocess.CalledProcessError(1, "gh"), zipfile.BadZipFile("bad"), RuntimeError("encrypted")):
            with self.subTest(error=type(error).__name__):
                self.archive_error = error
                self.assertFalse(self.resume())
                self.assertFalse(self.output.exists())
        self.archive_error = None
        self.artifact["expired"] = True
        self.assertFalse(self.resume())
        self.artifact["expired"] = False
        for name in ("../escaped", "/absolute", "nested/review.md"):
            with self.subTest(name=name):
                self.extra = [(name, "planted")]
                self.assertFalse(self.resume())
                self.assertFalse(self.output.exists())
        self.extra = []
        info = zipfile.ZipInfo("review.json")
        info.external_attr = 0o120777 << 16
        text = self.files.pop("review.json")
        self.extra = [(info, "../escaped")]
        self.assertFalse(self.resume())
        self.files["review.json"] = text

    def test_wrong_identity_and_changed_content_fail_digest_validation(self):
        for field, value in (("pr", 3), ("head", OTHER), ("base", OTHER), ("run", "101"), ("issues", [3])):
            with self.subTest(field=field):
                self.files["identity.json"] = json.dumps({**self.identity, field: value})
                self.assertFalse(self.resume())
                self.assertEqual(json.loads((self.input / "identity.json").read_text()), self.current)
        self.files["identity.json"] = json.dumps(self.identity)
        self.files["review.json"] = json.dumps({"verdict": "approve", "findings": [], "advisory": ["changed"]})
        self.assertFalse(self.resume())

    def test_credentials_anywhere_in_artifact_reject_reuse(self):
        original = copy.deepcopy(self.files)
        for name in self.files:
            with self.subTest(name=name):
                self.files = {**original, name: original[name] + f" {SECRET}"}
                self.assertFalse(self.resume())
                self.assertFalse(self.output.exists())
        self.files = original


if __name__ == "__main__":
    unittest.main()
