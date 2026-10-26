import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import test_control as base
import control

HEAD, OLD = "a" * 40, "b" * 40
REPO = "owner/tanomu"
PULL = {"head": {"sha": HEAD}}
BOT = {"login": "github-actions[bot]", "type": "Bot"}


class FinalReviewStatusTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.output = self.directory / "status.json"
        self.enterContext(mock.patch.dict(control.os.environ, {
            "GITHUB_REF": "refs/heads/main", "GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": "42"}))

    def status(self, posted, current=HEAD, inline=()):
        with mock.patch.object(control, "final_pull", return_value=(PULL | {"head": {"sha": current}}, [], posted)), \
                mock.patch.object(control, "posted_inline", return_value=set(inline)):
            return control.final_review_status("17", self.output)

    def test_distinguishes_current_stale_and_missing(self):
        cases = [([], "missing", None), ([[OLD, "1" * 16, 1, 1, "none"]], "stale", OLD),
                 ([[HEAD, "1" * 16, 1, 1, "none"]], "current", HEAD)]
        for posted, expected, reviewed in cases:
            with self.subTest(expected):
                result = self.status(posted)
                self.assertEqual(result, {"pr": 17, "head": HEAD, "status": expected, "reviewed_head": reviewed})
                self.assertEqual(json.loads(self.output.read_text()), result)

    def test_incomplete_or_old_inline_receipt_is_stale(self):
        for posted, inline in [([[HEAD, "1" * 16, 1, 2, "none"]], ()),
                               ([[HEAD, "1" * 16, 1, 1, "2" * 16]], ((OLD, "2" * 16),))]:
            with self.subTest(posted=posted):
                self.assertEqual(self.status(posted, inline=inline)["status"], "stale")

    def test_ineligible_pr_is_not_reported_as_missing(self):
        with mock.patch.object(control, "final_pull", return_value=(PULL, ["fork-pr"], [])):
            with self.assertRaisesRegex(ValueError, "fork-pr"):
                control.final_review_status("17", self.output)

    def report(self, expected, current, comments=()):
        status = self.directory / "expected.json"
        status.write_text(json.dumps(expected))
        pages = [[{"id": 8, "body": body, "user": BOT} for body in comments]]
        with mock.patch.object(control, "final_review_status", return_value=current), \
                mock.patch.object(control.subprocess, "check_output", return_value=json.dumps(pages)), \
                mock.patch.object(control.subprocess, "run") as run:
            result = control.agent_status_comment("17", status)
        return result, run

    def test_stale_report_updates_only_the_bot_status_comment(self):
        expected = {"pr": 17, "head": HEAD, "status": "stale", "reviewed_head": OLD}
        body = "<!-- tanomu-final-review-status -->\nold"
        result, run = self.report(expected, expected, [body])
        self.assertTrue(result)
        args = run.call_args.args[0]
        self.assertEqual(args[:4], ["gh", "api", "--method", "PATCH"])
        self.assertEqual(args[4], f"repos/{REPO}/issues/comments/8")
        payload = json.loads(run.call_args.kwargs["input"])["body"]
        self.assertIn(HEAD, payload)
        self.assertIn(OLD, payload)
        self.assertIn("gh workflow run agent-review.yml", payload)
        self.assertIn("Advisory only", payload)
        self.assertIn("Agent review is stale", payload)

    def test_incomplete_report_does_not_claim_an_older_head(self):
        current = {"pr": 17, "head": HEAD, "status": "stale", "reviewed_head": HEAD}
        result, run = self.report(current, current)
        self.assertTrue(result)
        payload = json.loads(run.call_args.kwargs["input"])["body"]
        self.assertIn("incomplete", payload)
        self.assertNotIn("latest published review belongs", payload)

    def test_initial_current_or_missing_report_does_not_create_a_comment(self):
        for status, reviewed in (("current", HEAD), ("missing", None)):
            with self.subTest(status=status):
                current = {"pr": 17, "head": HEAD, "status": status, "reviewed_head": reviewed}
                result, run = self.report(current, current)

                self.assertTrue(result)
                run.assert_not_called()

    def test_missing_report_updates_an_existing_status_comment(self):
        current = {"pr": 17, "head": HEAD, "status": "missing", "reviewed_head": None}
        result, run = self.report(current, current, ["<!-- tanomu-final-review-status -->\ncurrent"])

        self.assertTrue(result)
        self.assertEqual(run.call_args.args[0][3:5], ["PATCH", f"repos/{REPO}/issues/comments/8"])
        self.assertIn("No complete agent review", json.loads(run.call_args.kwargs["input"])["body"])

    def test_rechecks_after_reading_status_comments(self):
        expected = {"pr": 17, "head": OLD, "status": "stale", "reviewed_head": OLD}
        status = self.directory / "expected.json"
        status.write_text(json.dumps(expected))
        for change in ({"status": "current", "reviewed_head": OLD}, {"head": HEAD}):
            with self.subTest(change=change):
                live = dict(expected)

                def comments_changed(*args):
                    live.update(change)
                    return json.dumps([[]])

                with mock.patch.object(control, "final_review_status", side_effect=lambda number: dict(live)), \
                        mock.patch.object(control.subprocess, "check_output", side_effect=comments_changed), \
                        mock.patch.object(control.subprocess, "run") as run:
                    control.agent_status_comment("17", status)
                run.assert_not_called()

    def test_current_report_retires_an_existing_stale_comment(self):
        current = {"pr": 17, "head": HEAD, "status": "current", "reviewed_head": HEAD}
        result, run = self.report(current, current, ["<!-- tanomu-final-review-status -->\nstale"])
        self.assertTrue(result)
        payload = json.loads(run.call_args.kwargs["input"])["body"]
        self.assertIn("current", payload)
        self.assertNotIn("stale", payload)

    def test_moved_head_skips_the_status_write(self):
        expected = {"pr": 17, "head": OLD, "status": "stale", "reviewed_head": OLD}
        current = expected | {"head": HEAD}
        result, run = self.report(expected, current)
        self.assertFalse(result)
        run.assert_not_called()

    def test_public_marker_cannot_impersonate_the_bot(self):
        expected = {"pr": 17, "head": HEAD, "status": "stale", "reviewed_head": OLD}
        comments = [{"id": 8, "body": "<!-- tanomu-final-review-status -->", "user": {"login": "someone", "type": "User"}}]
        status = self.directory / "expected.json"
        status.write_text(json.dumps(expected))
        with mock.patch.object(control, "final_review_status", return_value=expected), \
                mock.patch.object(control.subprocess, "check_output", return_value=json.dumps([comments])), \
                mock.patch.object(control.subprocess, "run") as run:
            control.agent_status_comment("17", status)
        self.assertEqual(run.call_args.args[0][3], "POST")


class FinalReviewStatusWorkflowTest(unittest.TestCase):
    def test_status_is_separate_from_the_paid_review(self):
        workflow = base.WorkflowContractTest.load("agent-review-status.yml")
        triggers = workflow[True]["pull_request_target"]
        self.assertEqual(triggers["types"], ["opened", "synchronize", "reopened", "ready_for_review"])
        self.assertEqual(set(workflow["jobs"]), {"status"})
        job = workflow["jobs"]["status"]
        self.assertEqual(job["permissions"], {"contents": "read", "issues": "write", "pull-requests": "write"})
        self.assertNotIn("environment", job)
        text = json.dumps(workflow)
        self.assertNotIn("secrets.", text)
        self.assertNotIn("vars.", text)
        self.assertNotIn("agent_runner.py", text)
        self.assertNotIn("configure-claude", text)
        self.assertIn("head.repo.full_name == github.repository", job["if"])
        self.assertEqual(job["steps"][0]["with"], {"ref": "${{ github.sha }}", "persist-credentials": False})
        self.assertTrue(all(step["env"]["PR"] == "${{ github.event.pull_request.number || inputs.pr }}" for step in job["steps"][1:]))
        self.assertIn("final-review-status", job["steps"][1]["run"])
        self.assertIn("agent-status-comment", job["steps"][2]["run"])
        review = base.WorkflowContractTest.load("agent-review.yml")
        self.assertEqual(workflow["name"], "Agent PR review status")
        self.assertEqual(review["name"], "Agent PR review")
        observer = base.WorkflowContractTest.load("software-factory-observe.yml")
        self.assertEqual(observer[True]["workflow_run"]["workflows"],
                         ["Software factory implement", "Agent PR review", "Final PR review"])
        self.assertNotEqual(workflow["concurrency"]["group"], review["concurrency"]["group"])
        self.assertTrue(workflow["concurrency"]["cancel-in-progress"])
        self.assertIn("workflow_dispatch", workflow[True])
        self.assertIn("github.ref == 'refs/heads/main'", job["if"])

    def test_publisher_refreshes_status_after_inline_publication(self):
        workflow = base.WorkflowContractTest.load("agent-review.yml")
        steps = workflow["jobs"]["publish"]["steps"]
        refresh = steps[-1]
        self.assertEqual(refresh["name"], "Refresh advisory status")
        self.assertEqual(refresh["run"], 'gh workflow run agent-review-status.yml --ref main -f pr="$PR"')
        self.assertTrue(refresh["continue-on-error"])
        self.assertEqual(workflow["jobs"]["publish"]["permissions"]["actions"], "write")
        comment = next(step for step in steps if step.get("name") == "Comment on the PR")
        self.assertLess(steps.index(comment), steps.index(refresh))
        self.assertIn("inline.json", comment["run"])
        self.assertEqual(refresh["env"]["GH_TOKEN"], "${{ github.token }}")
