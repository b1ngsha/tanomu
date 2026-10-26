import copy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("reconcile", Path(__file__).with_name("reconcile.py"))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
REPO = "owner/repo"


def run(kind="implementation", **changes):
    return {"id": 10 if kind == "implementation" else 20, "run_attempt": 2, "workflow_id": 1 if kind == "implementation" else 2,
            "path": f".github/workflows/{r.FILES[kind]}", "head_repository": {"full_name": REPO},
            "head_branch": "main", "event": "workflow_dispatch", "actor": {"login": "owner"},
            "triggering_actor": {"login": "owner"}, "created_at": "2026-10-23T08:00:00Z",
            "updated_at": "2026-10-23T10:00:00Z", "status": "completed", "conclusion": "success",
            "display_title": "Factory issue #7 · attempt 2" if kind == "implementation" else "Final PR #9 · parent 10.2", **changes}


class Fake:
    def __init__(self, runs=None):
        self.calls, self.runs, self.overrides = [], runs or {}, {}
        self.pr = {"number": 9, "head": {"ref": "feat/7-implement", "repo": {"full_name": REPO}, "sha": "a" * 40},
                   "base": {"ref": "main", "repo": {"full_name": REPO}}}

    def __call__(self, path):
        self.calls.append(path)
        short = path.removeprefix(f"repos/{REPO}/")
        if short in self.overrides:
            value = self.overrides[short]
            if isinstance(value, Exception):
                raise value
            return copy.deepcopy(value)
        for kind, name in r.FILES.items():
            number = 1 if kind == "implementation" else 2
            if short == f"actions/workflows/{name}":
                return {"id": number, "path": f".github/workflows/{name}"}
            if short.startswith(f"actions/workflows/{number}/runs?"):
                return {"workflow_runs": self.runs.get(kind, [])}
        if "/jobs?" in short:
            return {"jobs": [{"name": "handoff" if "/10/" in short else "publish", "conclusion": "success"}]}
        if "/artifacts?" in short:
            return {"artifacts": []}
        if short == "issues/7":
            return {"user": {"login": "owner"}, "labels": [{"name": "implementing"}]}
        if short.startswith("pulls?"):
            return [self.pr]
        if short == "pulls/9":
            return self.pr
        if short == "actions/workflows/ci.yml":
            return {"id": 3, "path": ".github/workflows/ci.yml"}
        if short.startswith("actions/workflows/3/runs?"):
            return {"workflow_runs": [{"id": 30, "run_attempt": 1, "workflow_id": 3,
                     "path": ".github/workflows/ci.yml", "head_sha": "a" * 40,
                     "head_repository": {"full_name": REPO}, "event": "pull_request", "status": "in_progress"}]}
        if short.startswith("commits/"):
            return {"check_runs": [{"status": "in_progress"}]}
        raise AssertionError(short)


class ReconcileTests(unittest.TestCase):
    def test_correlated_child_and_safe_output(self):
        api = Fake({"implementation": [run()], "final-review": [run("final-review", actor={"login": "github-actions[bot]"})]})
        report = r.reconcile(api, REPO, NOW)
        parent, child = report["runs"]
        self.assertEqual(parent["final_review"], "observed")
        self.assertEqual(child["parent"], "observed")
        self.assertEqual(parent["ci"], "pending")
        self.assertEqual(parent["deploy"], "unavailable")
        self.assertIn("stale-implementing-label", parent["findings"])
        self.assertNotIn("final-review-not-observed", parent["findings"])
        self.assertFalse(any("download" in call or "comments" in call for call in api.calls))

    def test_agent_run_titles_keep_parent_correlation(self):
        api = Fake({"implementation": [run()], "final-review": [
            run("final-review", display_title="Agent PR #9 · parent 10.2")]})

        parent, child = r.reconcile(api, REPO, NOW)["runs"]

        self.assertEqual(parent["final_review"], "observed")
        self.assertEqual(child["parent"], "observed")
        self.assertIsNotNone(r.STANDALONE.fullmatch("Agent PR #9 · parent none"))

    def test_trust_fields_and_unrelated_events(self):
        for changes in ({"head_repository": {"full_name": "fork/repo"}}, {"workflow_id": 8}, {"path": "evil"},
                        {"actor": {"login": "other"}}, {"triggering_actor": {"login": "other"}},
                        {"head_branch": "evil"}, {"event": "pull_request"}):
            with self.subTest(changes=changes):
                self.assertEqual(r.reconcile(Fake({"implementation": [run(**changes)]}), REPO, NOW)["runs"], [])

    def test_stale_missing_child_and_unknown_identity(self):
        api = Fake({"implementation": [run(status="queued"), run(id=11, display_title="secret <script>")]})
        report = r.reconcile(api, REPO, NOW)
        self.assertIn("stale-implementation", report["runs"][0]["findings"])
        self.assertIn("final-review-not-observed", report["runs"][0]["findings"])
        self.assertNotIn("secret", str(report) + r.render(report))
        self.assertNotIn("issue", report["runs"][1])
        api.runs = {"implementation": [run(updated_at="2026-10-23T11:45:00Z")]}
        self.assertNotIn("final-review-not-observed", r.reconcile(api, REPO, NOW)["runs"][0]["findings"])

    def test_parent_attempt_branch_and_bot_are_not_guessed(self):
        api = Fake({"implementation": [run()], "final-review": [run("final-review", display_title="Final PR #9 · parent 10.1")]})
        report = r.reconcile(api, REPO, NOW)
        self.assertEqual(report["runs"][1]["parent"], "unknown")
        api.runs["final-review"] = [run("final-review", actor={"login": "github-actions[bot]"})]
        api.pr["head"]["ref"] = "feat/8-implement"
        self.assertEqual(len(r.reconcile(api, REPO, NOW)["runs"]), 1)

    def test_round_review_delivery_requires_claim_and_complete_jobs(self):
        api = Fake({"implementation": [run()]})
        path = "actions/runs/10/attempts/2/jobs?per_page=100&page=1"
        for claim, publish, conclusion, expected in (
                ('success', 'failure', 'failure', True), ('success', 'skipped', 'success', True),
                ('failure', 'skipped', 'failure', False), ('skipped', 'failure', 'failure', False),
                ('success', 'success', 'success', False), ('success', 'skipped', 'cancelled', False)):
            with self.subTest(claim=claim, publish=publish, conclusion=conclusion):
                api.runs['implementation'] = [run(conclusion=conclusion)]
                api.overrides[path] = {'jobs': [{'name': 'claim', 'conclusion': claim},
                                              {'name': 'publish-reviews', 'conclusion': publish}]}
                record = r.reconcile(api, REPO, NOW)['runs'][0]
                self.assertEqual('round-reviews-not-delivered' in record['findings'], expected)
        api.overrides[path] = RuntimeError('unavailable')
        self.assertNotIn('round-reviews-not-delivered', r.reconcile(api, REPO, NOW)['runs'][0]['findings'])

    def test_artifact_expiry_publish_failure_and_partial_api(self):
        api = Fake({"final-review": [run("final-review", display_title="Final PR #9 · parent none")]})
        api.overrides["actions/runs/20/artifacts?per_page=100&page=1"] = {"artifacts": [{"name": "final-review", "expired": True}]}
        api.overrides["actions/runs/20/attempts/2/jobs?per_page=100&page=1"] = {"jobs": [{"name": "publish", "conclusion": "failure"}]}
        report = r.reconcile(api, REPO, NOW)
        self.assertEqual(report["runs"][0]["artifacts"]["final-review"], ["recorded-expired"])
        self.assertIn("final-review-not-delivered", report["runs"][0]["findings"])
        api.overrides["actions/runs/20/attempts/2/jobs?per_page=100&page=1"] = RuntimeError("secret")
        report = r.reconcile(api, REPO, NOW)
        self.assertIn("api-partial-failure", report["notices"])
        self.assertEqual(report["runs"][0]["findings"], ["evidence-expired"])
        self.assertEqual(report["runs"][0]["pr"], 9)
        api.overrides["actions/runs/20/attempts/2/jobs?per_page=100&page=1"] = {"jobs": [
            {"name": name, "conclusion": conclusion} for name, conclusion in (("identify", "success"), ("review", "skipped"), ("publish", "skipped"))]}
        self.assertNotIn("final-review-not-delivered", r.reconcile(api, REPO, NOW)["runs"][0]["findings"])
        self.assertNotIn("secret", str(report))

    def test_expiry_in_round_evidence_including_historical_rounds_is_observed(self):
        api = Fake({"implementation": [run()]})
        for name in ('session-implement-1', 'session-review-2', 'feedback-2', 'checked-2',
                     'session-review-4', 'feedback-4', 'checked-4'):
            with self.subTest(name=name):
                api.overrides['actions/runs/10/artifacts?per_page=100&page=1'] = {'artifacts': [
                    {'name': name, 'expired': True}, {'name': 'secret-prompt', 'expired': True}]}
                record = r.reconcile(api, REPO, NOW)['runs'][0]
                self.assertIn('evidence-expired', record['findings'])
                self.assertEqual(record['artifacts'][name], ['recorded-expired'])
                self.assertNotIn('secret', str(record))
                self.assertFalse(any('/zip' in call or '/logs' in call for call in api.calls))

    def test_jobs_budget_and_unrelated_issue_labels(self):
        api = Fake({"implementation": [run(event="issues")]})
        path = "actions/runs/10/attempts/2/jobs?per_page=100&page="
        api.overrides[path + "1"] = {"jobs": [{"name": "gate", "conclusion": "skipped"}]}
        self.assertEqual(r.reconcile(api, REPO, NOW)["runs"], [])
        for page in range(1, 4):
            api.overrides[path + str(page)] = {"jobs": [{"name": "gate", "conclusion": "success"}] * 100}
        self.assertIn("jobs-scan-limited", r.reconcile(api, REPO, NOW)["notices"])
        self.assertFalse(any("page=4" in call for call in api.calls))

    def test_unrelated_green_checks_do_not_claim_ci_success(self):
        api = Fake({"implementation": [run()]})
        api.overrides['commits/' + 'a' * 40 + '/check-runs?per_page=100&page=1'] = {"check_runs": [{"status": "completed", "conclusion": "success"}]}
        api.overrides['actions/workflows/3/runs?head_sha=' + 'a' * 40 + '&per_page=100&page=1'] = {"workflow_runs": [
            {"id": 30, "workflow_id": 99, "path": ".github/workflows/unrelated.yml", "head_sha": "a" * 40,
             "head_repository": {"full_name": REPO}, "event": "pull_request", "status": "completed", "conclusion": "success"}]}
        self.assertEqual(r.reconcile(api, REPO, NOW)['runs'][0]['ci'], 'unavailable')

    def test_current_parent_attempt_cannot_bind_historical_child(self):
        api = Fake({"implementation": [run(run_attempt=3, display_title="Factory issue #7 · attempt 3")],
                    "final-review": [run("final-review", actor={"login": "github-actions[bot]"})]})
        report = r.reconcile(api, REPO, NOW)
        self.assertEqual(len(report["runs"]), 1)
        self.assertEqual(report["runs"][0]["final_review"], "unknown")
        self.assertIn("final-review-not-observed", report["runs"][0]["findings"])

    def test_bounded_scan_and_age(self):
        api = Fake({"implementation": [run(id=n) for n in range(1, 101)]})
        report = r.reconcile(api, REPO, NOW)
        self.assertEqual(len(report["runs"]), 20)
        self.assertEqual(len([p for p in api.calls if "/workflows/1/runs?" in p]), 3)
        self.assertIn("run-detail-limited", report["notices"])
        self.assertLessEqual(report["requests"], 300)
        self.assertEqual(r.reconcile(Fake({"implementation": [run(created_at="2025-01-01T00:00:00Z")]}), REPO, NOW)["runs"], [])


if __name__ == "__main__":
    unittest.main()
