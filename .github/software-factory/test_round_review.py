import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import control


class RepairContextTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        (self.repo / "a.txt").write_text("base\n")
        self.git("add", "a.txt")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=self.repo,
                              check=True, capture_output=True, text=True).stdout.strip()

    def candidate(self, number, text):
        (self.repo / "a.txt").write_text(text)
        patch = self.git("diff", "--binary", self.base) + "\n"
        directory = self.root / f"checked-{number}"
        directory.mkdir()
        (directory / "candidate.patch").write_text(patch)
        self.git("checkout", "--", "a.txt")

    def repair(self, round_number):
        previous = Path.cwd()
        try:
            os.chdir(self.repo)
            return control.repair_context(self.base, round_number, self.root, self.root / "out")
        finally:
            os.chdir(previous)

    def test_stages_the_last_review_and_the_delta_since_it(self):
        self.candidate(1, "one\n")
        self.candidate(2, "two\n")
        feedback = self.root / "feedback-1"
        feedback.mkdir()
        (feedback / "review.json").write_text('{"findings":["Standards: old"],"advisory":[]}')

        self.assertTrue(self.repair("2"))

        repair = (self.root / "out/repair.patch").read_text()
        self.assertIn("-one", repair)
        self.assertIn("+two", repair)
        self.assertNotIn("base", repair)
        self.assertEqual(json.loads((self.root / "out/previous-review.json").read_text())["findings"],
                         ["Standards: old"])

    def test_uses_the_latest_round_that_actually_had_a_review(self):
        self.candidate(1, "one\n")
        self.candidate(2, "two\n")
        self.candidate(3, "three\n")
        (self.root / "feedback-1").mkdir()
        (self.root / "feedback-1/review.json").write_text('{"findings":[],"advisory":[]}')
        (self.root / "feedback-2").mkdir()
        (self.root / "feedback-2/checks.json").write_text('{"command":"pnpm test"}')

        self.assertTrue(self.repair("3"))
        self.assertIn("+three", (self.root / "out/repair.patch").read_text())

    def test_without_a_previous_review_uses_the_full_prompt(self):
        self.candidate(1, "one\n")
        self.assertFalse(self.repair("2"))
        self.assertFalse((self.root / "out/previous-review.json").exists())


class VerifierTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def result(self, value, name="result.json"):
        path = self.root / name
        path.write_text(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                                    "structured_output": value}))
        return str(path)

    def test_verdicts_must_cover_each_claim_exactly_once(self):
        claims = ["Standards: bug", "Spec: missing"]
        valid = self.result({"verdicts": [{"id": 0, "confirmed": False, "evidence": "not introduced"},
                                          {"id": 1, "confirmed": True, "evidence": "a.ts:4"}]})
        self.assertEqual(control.claude_verdicts(valid, claims), {0: (False, "not introduced"),
                                                                  1: (True, "a.ts:4")})
        for verdicts in ([{"id": 0, "confirmed": False, "evidence": "x"}],
                         [{"id": 0, "confirmed": False, "evidence": "x"},
                          {"id": 0, "confirmed": True, "evidence": "y"},
                          {"id": 1, "confirmed": True, "evidence": "z"}],
                         [{"id": 2, "confirmed": True, "evidence": "x"},
                          {"id": 1, "confirmed": True, "evidence": "y"}]):
            with self.subTest(verdicts=verdicts):
                with self.assertRaisesRegex(ValueError, "invalid-verdicts"):
                    control.claude_verdicts(self.result({"verdicts": verdicts}), claims)

    def test_unconfirmed_blocking_findings_become_advisory(self):
        claims = ["Standards: bug"]
        findings = self.result({"findings": [{"blocking": True, "finding": "bug",
                                              "path": "a.ts", "line": 4}]}, "axis.json")
        report = control.claude_review_result([("Standards", findings)], self.root / "review.json",
                                              {"Standards: bug": (False, "not in the diff")})
        self.assertEqual(report["verdict"], "approve")
        self.assertEqual(report["findings"], [])
        self.assertIn("Unconfirmed by verification: not in the diff", report["advisory"][0])

    def test_repair_prompt_is_explicit_and_requires_locations(self):
        full = control.prompt("review-spec", "1", "false")
        repair = control.prompt("review-spec", "1", "true")
        self.assertNotIn("previous-review.json", full)
        self.assertIn("previous-review.json", repair)
        self.assertIn("repair.patch", repair)
        self.assertIn('"path":"file.ts"', repair)
        self.assertIn("Pre-existing:", repair)

    def test_round_status_exposes_verifier_outcome(self):
        jobs = {"review": {"outputs": {"standards": "passed", "spec": "passed", "verify": "skipped"}}}
        self.assertIn("verify=skipped", control.round_status(jobs))


if __name__ == "__main__":
    unittest.main()
