import importlib.util
import unittest
from unittest import mock
from pathlib import Path

spec = importlib.util.spec_from_file_location("observe", Path(__file__).with_name("observe.py"))
observe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observe)


class ObservationTest(unittest.TestCase):
    def test_successful_delivery_keeps_independent_review_pending(self):
        record = observe.summarize_jobs([
            {"name": "handoff", "status": "completed", "conclusion": "success"},
            {"name": "publish-reviews", "status": "in_progress", "conclusion": None},
        ], "implement")
        self.assertEqual(record["delivery"], "success")
        self.assertEqual(record["final_review"], "pending-separate-run")
        self.assertEqual(record["review_comments"], "in_progress")
        self.assertEqual(record["phase"], "publish-reviews")

    def test_candidate_names_and_reason_text_never_enter_metadata(self):
        record = observe.summarize_jobs([
            {"name": "secret-prompt", "status": "in_progress", "conclusion": "provider secret"},
            {"name": "round1 / review", "status": "completed", "conclusion": "failure"},
        ], "implement")
        self.assertNotIn("secret", str(record))
        self.assertEqual(record["jobs"], {"round1 / review": "failure"})

    def test_unrelated_events_and_untrusted_runs_are_summary_only(self):
        run = {"head_branch": "main", "event": "issues", "actor": {"login": "owner"},
               "triggering_actor": {"login": "owner"}, "head_repository": {"full_name": "owner/repo"},
               "path": ".github/workflows/software-factory-implement.yml",
               "display_title": "Factory issue #10 · attempt 1"}
        self.assertEqual(observe.identity(run, "owner/repo"), ("implement", "10", None))
        run["actor"]["login"] = "public"
        self.assertIsNone(observe.identity(run, "owner/repo"))

    def test_final_identity_keeps_explicit_parent_attempt(self):
        run = {"head_branch": "main", "event": "workflow_dispatch", "actor": {"login": "owner"},
               "triggering_actor": {"login": "owner"}, "head_repository": {"full_name": "owner/repo"},
               "path": ".github/workflows/final-review.yml",
               "display_title": "Final PR #12 · parent 123.2"}
        self.assertEqual(observe.identity(run, "owner/repo"), ("final-review", "12", "123.2"))
    def test_snapshot_uses_trusted_jobs_and_never_candidate_artifacts(self):
        run = {"head_branch": "main", "event": "issues", "actor": {"login": "owner"},
               "triggering_actor": {"login": "owner"}, "head_repository": {"full_name": "owner/repo"},
               "path": ".github/workflows/software-factory-implement.yml", "workflow_id": 7,
               "display_title": "Factory issue #10 · attempt 1", "run_attempt": 1,
               "head_sha": "a" * 40, "status": "in_progress"}
        calls = []

        def api(path):
            calls.append(path)
            if path.endswith('/runs/123'):
                return run
            if '/workflows/' in path:
                return {"id": 7}
            if path.endswith('/issues/10'):
                return {"user": {"login": "owner"}}
            if '/jobs?' in path:
                return {"jobs": [{"name": "gate", "conclusion": "success"},
                                 {"name": "round1 / implement", "status": "in_progress"}]}
            if '/pulls?' in path:
                return []
            if '/artifacts?' in path:
                return {"artifacts": []}
            self.fail(path)
        result = observe.snapshot(api, "owner/repo", "123")
        self.assertEqual(result['issue'], 10)
        self.assertEqual(result['phase'], 'round1 / implement')
        self.assertEqual(result['state'], 'in_progress')
        self.assertEqual(result['evidence_state'], 'unavailable-not-proof-never-produced')
        self.assertTrue(all(path.endswith(('per_page=100&page=1', '/runs/123', '/software-factory-implement.yml', '/issues/10', 'per_page=20')) for path in calls))
        self.assertIsNone(result['current_head'])
        self.assertIsNone(result['reviewed_head'])
        run.update(status='completed', conclusion='failure')
        job_rows = [{'name': 'gate', 'conclusion': 'success'}, {'name': 'claim', 'conclusion': 'success'},
                    {'name': 'publish-reviews', 'conclusion': 'failure'}]
        def failed_api(path):
            return {'jobs': job_rows} if '/jobs?' in path else api(path)
        result = observe.snapshot(failed_api, 'owner/repo', '123')
        self.assertEqual(result['findings'], ['round-reviews-not-delivered'])
        self.assertEqual(result['review_comments'], 'failure')
        self.assertEqual(result['state'], 'failure')
        job_rows[1]['conclusion'] = 'failure'
        self.assertEqual(observe.snapshot(failed_api, 'owner/repo', '123')['findings'], [])
        job_rows[1]['conclusion'] = 'success'
        job_rows += [{'name': 'round2 / review', 'conclusion': 'skipped'}] * 97
        result = observe.snapshot(failed_api, 'owner/repo', '123')
        self.assertFalse(result['jobs_complete'])
        self.assertEqual(result['findings'], [])
        run['workflow_id'] = 8
        self.assertIsNone(observe.snapshot(api, "owner/repo", "123"))

    def test_bot_final_child_requires_successful_exact_parent_and_task_branch(self):
        child = {"head_branch": "main", "event": "workflow_dispatch", "actor": {"login": "github-actions[bot]"},
                 "triggering_actor": {"login": "github-actions[bot]"}, "head_repository": {"full_name": "owner/repo"},
                 "path": ".github/workflows/final-review.yml", "workflow_id": 8,
                 "display_title": "Final PR #12 · parent 123.2", "run_attempt": 1, "status": "completed", "conclusion": "success"}
        parent = {**child, "actor": {"login": "owner"}, "triggering_actor": {"login": "owner"},
                  "path": ".github/workflows/software-factory-implement.yml", "workflow_id": 7,
                  "display_title": "Factory issue #10 · attempt 2", "run_attempt": 2}
        pull = {"user": {"login": "github-actions[bot]"}, "head": {"repo": {"full_name": "owner/repo"},
                "ref": "feat/10-implement", "sha": "b" * 40}, "base": {"ref": "main", "repo": {"full_name": "owner/repo"}, "sha": "a" * 40}}
        handoff = "success"
        current_attempt = 2

        def api(path):
            if path.endswith('/runs/123'):
                return {**parent, "run_attempt": current_attempt}
            if path.endswith('/runs/456'):
                return child
            if path.endswith('/123/attempts/2'):
                return parent
            if '/workflows/' in path:
                return {"id": 7 if 'implement' in path else 8}
            if path.endswith('/pulls/12'):
                return pull
            if '/123/attempts/2/jobs?' in path:
                return {"jobs": [{"name": "handoff", "conclusion": handoff}]}
            if '/jobs?' in path:
                return {"jobs": [{"name": "publish", "conclusion": "success"}]}
            if '/artifacts?' in path:
                return {"artifacts": []}
            self.fail(path)
        before = observe.snapshot(api, 'owner/repo', '456')
        self.assertEqual(before['parent'], '123.2')
        self.assertEqual(before['current_head'], 'b' * 40)
        self.assertEqual(before['current_base'], 'a' * 40)
        pull['head']['sha'], pull['base']['sha'] = 'c' * 40, 'd' * 40
        after = observe.snapshot(api, 'owner/repo', '456')
        self.assertEqual((after['current_head'], after['current_base']), ('c' * 40, 'd' * 40))
        self.assertIsNone(before['reviewed_head'])
        self.assertIsNone(after['reviewed_head'])
        self.assertIsNone(after['reviewed_base'])
        self.assertIn('Reviewed head/base: unknown / unknown', observe.render(after))
        current_attempt = 3
        self.assertIsNone(observe.snapshot(api, 'owner/repo', '456'))
        current_attempt = 2
        handoff = 'failure'
        self.assertIsNone(observe.snapshot(api, 'owner/repo', '456'))
        handoff = 'success'
        pull['head']['ref'] = 'feat/11-implement'
        self.assertIsNone(observe.snapshot(api, 'owner/repo', '456'))

    def test_existing_comment_after_300_is_updated_and_lookup_failure_never_posts(self):
        record = {"repository": "owner/repo", "run_id": 123, "kind": "implement", "issue": 10, "pr": None}
        marker = '<!-- factory-observation:implement:123 -->'
        filler = [{"body": marker, "user": {"login": "public", "type": "User"}}] * 100
        existing = {"id": 6, "body": marker + '\nold', "user": {"login": "github-actions[bot]", "type": "Bot"}}
        with mock.patch.object(observe, 'get', side_effect=[filler] * 3 + [[existing]]), mock.patch.object(
                observe, 'render', return_value='status'), mock.patch.object(observe.subprocess, 'run') as call:
            observe.publish(record)
            self.assertIn('PATCH', call.call_args.args[0])
            self.assertIn('repos/owner/repo/issues/comments/6', call.call_args.args[0])
        with mock.patch.object(observe, 'get', side_effect=[filler] * 3 + [RuntimeError('unavailable')]), mock.patch.object(
                observe, 'render', return_value='status'), mock.patch.object(observe.subprocess, 'run') as call:
            with self.assertRaises(RuntimeError):
                observe.publish(record)
            call.assert_not_called()

    def test_comment_marker_owned_by_bot_and_deduplicated(self):
        record = {"repository": "owner/repo", "run_id": 123, "kind": "implement", "issue": 10, "pr": None}
        marker = '<!-- factory-observation:implement:123 -->\nstatus'
        comments = [{"id": 5, "body": marker, "user": {"login": "public", "type": "User"}}]
        with mock.patch.object(observe, 'get', return_value=comments), mock.patch.object(observe, 'render', return_value='status'), mock.patch.object(observe.subprocess, 'run') as call:
            observe.publish(record)
            self.assertIn('POST', call.call_args.args[0])
            comments.append({"id": 6, "body": marker, "user": {"login": "github-actions[bot]", "type": "Bot"}})
            call.reset_mock()
            observe.publish(record)
            call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
