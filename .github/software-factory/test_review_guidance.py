import copy
import json
import unittest
from unittest import mock

import control
import publication
import test_control as base


class ReviewGuidanceTest(unittest.TestCase):
    def test_every_axis_loads_repository_review_guidance(self):
        for axis in ("standards", "spec", "security"):
            with self.subTest(axis=axis):
                text = control.prompt(f"final-{axis}", "b" * 40, "a" * 40)
                self.assertIn("What failure looks like", text)
                self.assertIn("Nit:", text)
        self.assertIn("trust boundaries", control.prompt("final-security", "b" * 40, "a" * 40))

    def test_nit_cap_only_changes_the_summary(self):
        result = {"findings": [], "advisory": [f"Standards: Nit: cleanup {n}" for n in range(7)]}
        original = copy.deepcopy(result)

        summary = publication.compact_summary(result, [])

        self.assertEqual(result, original)
        for n in range(5):
            self.assertIn(f"cleanup {n}", summary)
        self.assertNotIn("cleanup 5", summary)
        self.assertNotIn("cleanup 6", summary)
        self.assertIn("2 additional nit findings", summary)
        self.assertIn("0 blocking, 7 advisory", summary)

    def test_important_and_preexisting_findings_are_not_capped(self):
        result = {"findings": [], "advisory": [f"Spec: Important: consequence {n}" for n in range(6)]
                  + [f"Standards: Pre-existing: old {n}" for n in range(6)]}
        summary = publication.compact_summary(result, [])
        self.assertTrue(all(f"consequence {n}" in summary for n in range(6)))
        self.assertTrue(all(f"old {n}" in summary for n in range(6)))


class SecurityPathTest(unittest.TestCase):
    def paths(self, value):
        with mock.patch.object(control, "git", return_value=value.encode()) as git:
            result = control.security_required("a" * 40, "b" * 40)
        self.assertEqual(git.call_args.args[:4], ("diff", "--name-only", "-z", "--no-ext-diff"))
        return result

    def test_sensitive_paths_enable_the_axis(self):
        for paths in (".github/workflows/ci.yml\0README.md\0",
                      "deploy/compose.yml\0",
                      "apps/server/src/key-cipher.ts\0",
                      "apps/server/src/provider-store.ts\0",
                      "apps/server/src/feishu-oauth.ts\0",
                      "apps/server/src/main.ts\0",
                      "apps/admin/src/auth-form.tsx\0"):
            with self.subTest(paths=paths):
                self.assertTrue(self.paths(paths))

    def test_ordinary_changes_skip_the_axis(self):
        self.assertFalse(self.paths("apps/server/src/chat.ts\0docs/software-factory.md\0"))

    def test_malformed_revisions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid-sha"):
            control.security_required("HEAD", "b" * 40)


class SecurityWorkflowContractTest(unittest.TestCase):
    def test_security_classification_precedes_the_review_and_uses_trusted_code(self):
        workflow = base.WorkflowContractTest.load("agent-review.yml")
        steps = workflow["jobs"]["review"]["steps"]
        names = [step.get("name") for step in steps]
        classify = next(step for step in steps if step.get("id") == "security")
        review = next(step for step in steps if step.get("name") == "Review the pull request")
        self.assertLess(names.index("Classify security-sensitive paths"), names.index("Review the pull request"))
        self.assertIn("control.py security-required", classify["run"])
        self.assertEqual(classify["working-directory"], "candidate")
        self.assertEqual(review["env"]["SECURITY"], "${{ steps.security.outputs.required }}")
        self.assertIn("${SECURITY:-false}", review["run"])
        self.assertNotIn("secrets.", json.dumps(classify))


if __name__ == "__main__":
    unittest.main()
