import json
import os
import unittest
from unittest import mock

import control
import test_control as base
from test_control import REPO, TaskDirectory

HEAD, BASE, OTHER = "a" * 40, "b" * 40, "c" * 40


class EvalIdentifyTest(TaskDirectory):
    def setUp(self):
        super().setUp()
        self.output = self.root / "eval-input"
        self.case = {"id": "known-defect", "pr": 97, "head": HEAD, "base": BASE,
                     "fix_pr": 105, "clean": False,
                     "expected": [{"path": "workflow.yml", "contains": "permission"}]}
        self.cases = self.root / "evals.json"
        self.cases.write_text(json.dumps({"version": 1, "cases": [self.case]}))
        self.enterContext(mock.patch.object(control, "EVALS_FILE", self.cases))
        self.enterContext(mock.patch.dict(os.environ, {"GITHUB_REF": "refs/heads/main",
                                                       "GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": "123"}))
        self.pull = {"merged": True, "head": {"sha": HEAD, "repo": {"full_name": REPO}},
                     "base": {"ref": "main", "sha": BASE, "repo": {"full_name": REPO}},
                     "body": "Refs #3"}

    def api(self, path):
        if path == f"repos/{REPO}/pulls/97":
            return self.pull
        if path == f"repos/{REPO}/compare/{BASE}...{HEAD}":
            return {"merge_base_commit": {"sha": BASE}}
        if path == f"repos/{REPO}/issues/3":
            return {"title": "Known defect", "body": "Do it.",
                    "repository_url": f"https://api.github.com/repos/{REPO}"}
        raise AssertionError(path)

    def identify(self):
        with mock.patch.object(control, "api", self.api):
            return control.eval_identify("known-defect", self.output)

    def test_resolves_the_pinned_revision_and_linked_spec(self):
        self.assertEqual(self.identify(), {"pr": "97", "head": HEAD, "base": BASE, "spec": "true"})
        self.assertEqual(json.loads((self.output / "case.json").read_text()), self.case)
        self.assertEqual(json.loads((self.output / "identity.json").read_text()), {
            "pr": 97, "head": HEAD, "base": BASE, "issues": [3], "run": "123",
            "summary_format": "compact", "review_name": "Agent review evaluation"})
        self.assertIn("Known defect", (self.output / "issue-3.md").read_text())

    def test_rejects_a_moved_or_unmerged_historical_revision(self):
        for change, reason in (
            (lambda: self.pull.update(merged=False), "eval-not-merged"),
            (lambda: self.pull["head"].update(sha=OTHER), "eval-revision-moved"),
            (lambda: self.pull["base"].update(sha=OTHER), "eval-revision-moved"),
            (lambda: self.pull["head"].update(repo=None), "fork-pr"),
            (lambda: self.pull["base"].update(ref="next"), "wrong-base"),
            (lambda: os.environ.update(GITHUB_REF="refs/heads/next"), "wrong-ref"),
        ):
            with self.subTest(reason=reason):
                original = json.loads(json.dumps(self.pull))
                change()
                self.assertRejects(reason, self.identify)
                self.pull = original

    def test_rejects_a_changed_merge_base(self):
        def changed(path):
            result = self.api(path)
            if path.startswith(f"repos/{REPO}/compare/"):
                result["merge_base_commit"]["sha"] = OTHER
            return result

        with mock.patch.object(control, "api", changed):
            self.assertRejects("eval-revision-moved", control.eval_identify, "known-defect", self.output)

    def update_case(self, **changes):
        self.case.update(changes)
        self.cases.write_text(json.dumps({"version": 1, "cases": [self.case]}))

    def test_rejects_ambiguous_or_unpinned_cases(self):
        for change in (
            lambda: self.update_case(head="HEAD"),
            lambda: self.update_case(base=None),
            lambda: self.update_case(clean="yes"),
            lambda: self.update_case(expected=[{"path": "workflow.yml"}]),
            lambda: self.cases.write_text(json.dumps({"cases": [self.case, self.case]})),
        ):
            with self.subTest(change=change):
                original = json.loads(json.dumps(self.case))
                original_file = self.cases.read_text()
                change()
                self.assertRejects("invalid-eval-case", self.identify)
                self.case = original
                self.cases.write_text(original_file)


class EvalScoreTest(TaskDirectory):
    def setUp(self):
        super().setUp()
        self.case = self.root / "case.json"
        self.case.write_text(json.dumps({"id": "known-defect", "pr": 97, "clean": False,
                                         "expected": [{"path": "workflow.yml", "contains": "permission"}]}))
        self.output = self.root / "score.json"

    def result(self, findings, name="standards.json"):
        path = self.root / name
        path.write_text(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                                    "structured_output": {"findings": findings}}))
        return path

    def finding(self, text, path="workflow.yml", blocking=True):
        return {"finding": text, "path": path, "line": 1, "blocking": blocking}

    def test_scores_expected_evidence_without_echoing_findings(self):
        result = self.result([self.finding("PERMISSION is insufficient")])
        score = control.eval_score(self.case, self.output, result)
        self.assertEqual(score, {"case": "known-defect", "pr": 97, "expected": 1, "hits": 1,
                                 "misses": [], "findings": 1, "blocking": 1, "clean": False, "passed": True})
        self.assertNotIn("PERMISSION is insufficient", self.output.read_text())

    def test_requires_both_the_expected_text_and_path(self):
        result = self.result([self.finding("permission is insufficient", path="other.yml")])
        score = control.eval_score(self.case, self.output, result)
        self.assertEqual(score["misses"], [0])
        self.assertFalse(score["passed"])

    def test_clean_cases_reject_only_blocking_false_positives(self):
        self.case.write_text(json.dumps({"id": "clean-fix", "pr": 105, "clean": True, "expected": []}))
        advisory = self.result([self.finding("Nit: naming", blocking=False)])
        self.assertTrue(control.eval_score(self.case, self.output, advisory)["passed"])

        blocking = self.result([self.finding("False positive")], "security.json")
        score = control.eval_score(self.case, self.output, advisory, blocking)
        self.assertEqual(score["blocking"], 1)
        self.assertFalse(score["passed"])


class EvalWorkflowContractTest(unittest.TestCase):
    def setUp(self):
        self.workflow = base.WorkflowContractTest.load("agent-review-eval.yml")
        self.jobs = self.workflow["jobs"]

    def test_manual_main_only_and_read_only(self):
        self.assertEqual(set(self.workflow[True]), {"workflow_dispatch"})
        self.assertEqual(self.jobs["identify"]["if"], "github.ref == 'refs/heads/main'")
        self.assertEqual(self.workflow["permissions"], {})
        self.assertEqual(self.jobs["identify"]["permissions"],
                         {"contents": "read", "issues": "read", "pull-requests": "read"})
        self.assertEqual(self.jobs["review"]["permissions"], {"contents": "read"})
        text = json.dumps(self.workflow)
        for forbidden in ("gh pr comment", "final-comments", "pull-requests: write", "issues: write"):
            self.assertNotIn(forbidden, text)

    def test_identification_and_model_credentials_are_separate(self):
        identify = json.dumps(self.jobs["identify"])
        review = json.dumps(self.jobs["review"])
        self.assertNotIn("secrets.", identify)
        self.assertIn("secrets.AGENT_API_KEY", review)
        self.assertNotIn("GH_TOKEN", review)
        self.assertNotIn("github.token", review)
        self.assertEqual(self.jobs["review"]["needs"], "identify")
        self.assertEqual(self.jobs["review"]["environment"], "agent")
        candidate = next(step for step in self.jobs["review"]["steps"]
                         if step.get("with", {}).get("path") == "candidate")
        self.assertEqual(candidate["with"]["ref"], "${{ needs.identify.outputs.head }}")
        self.assertIs(candidate["with"]["persist-credentials"], False)

    def test_reviews_scores_and_uploads_without_publishing_model_text(self):
        steps = self.jobs["review"]["steps"]
        names = [step.get("name", step.get("uses")) for step in steps]
        review = next(step for step in steps if step.get("name") == "Review the historical diff")
        score = next(step for step in steps if step.get("id") == "score")
        self.assertIn('agent_runner.py final 600 -- "$BASE" "$HEAD" "$SPEC" "${SECURITY:-false}"', review["run"])
        self.assertIn("eval-score", score["run"])
        self.assertIn("scan-output", score["run"])
        self.assertIn("Blocking:", score["run"])
        self.assertNotIn("review.json", score["run"].splitlines()[-1])
        self.assertLess(names.index("Review the historical diff"), names.index("Score expected evidence"))
        failure = next(step for step in steps if step.get("name") == "Fail on missed expected evidence")
        self.assertIn("steps.score.outputs.passed != 'true'", failure["if"])

    def test_artifacts_are_explicit_and_short_lived(self):
        uploads = [step for job in self.jobs.values() for step in job["steps"]
                   if "upload-artifact" in step.get("uses", "")]
        self.assertEqual({step["with"]["name"] for step in uploads}, {"eval-input", "agent-review-evaluation"})
        for step in uploads:
            with self.subTest(artifact=step["with"]["name"]):
                self.assertEqual(step["with"]["retention-days"], 3)
                self.assertEqual(step["with"]["if-no-files-found"], "error")


if __name__ == "__main__":
    unittest.main()
