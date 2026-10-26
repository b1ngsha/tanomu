"""Exercise the real trusted entry points from an untrusted candidate cwd."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from execution import job_states, publication_findings


class ExecutionTests(unittest.TestCase):
    def test_native_states_and_publication_policy(self):
        states = job_states([{'name': 'claim', 'conclusion': 'success'},
                             {'name': 'publish-reviews', 'status': 'in_progress'},
                             {'name': 'round4 / review', 'conclusion': 'failure'}])
        self.assertEqual(states['publish-reviews'], 'in_progress')
        self.assertEqual(states['round4 / review'], 'failure')
        self.assertEqual(publication_findings('implement', 'in_progress', None, states, True), [])
        self.assertEqual(publication_findings('implement', 'completed', 'failure', states, False), [])
        self.assertEqual(publication_findings('implement', 'completed', 'failure', states, True), ['round-reviews-not-delivered'])
        for status, conclusion in (('queued', None), ('completed', 'cancelled')):
            self.assertEqual(publication_findings('implementation', status, conclusion, states, True), [])
        deduplicated = {'identify': 'success', 'review': 'skipped', 'publish': 'skipped'}
        self.assertEqual(publication_findings('final-review', 'completed', 'success', deduplicated, True), [])
        deduplicated['publish'] = 'failure'
        self.assertEqual(publication_findings('final-review', 'completed', 'failure', deduplicated, True), ['final-review-not-delivered'])

    def test_isolated_entries_from_candidate_cwd_use_only_trusted_metadata(self):
        repo = 'owner/repo'
        now = datetime.now(timezone.utc).isoformat()
        run = {'id': 10, 'run_attempt': 2, 'workflow_id': 1,
               'path': '.github/workflows/software-factory-implement.yml',
               'head_repository': {'full_name': repo}, 'head_branch': 'main', 'head_sha': 'a' * 40,
               'event': 'workflow_dispatch', 'actor': {'login': 'owner'}, 'triggering_actor': {'login': 'owner'},
               'display_title': 'Factory issue #7 · attempt 2', 'created_at': now, 'updated_at': now,
               'status': 'completed', 'conclusion': 'failure'}
        fixtures = {
            'actions/runs/10': run,
            'actions/workflows/software-factory-implement.yml': {'id': 1, 'path': run['path']},
            'actions/workflows/agent-review.yml': {'id': 2, 'path': '.github/workflows/agent-review.yml'},
            'actions/workflows/final-review.yml': {'id': 4, 'path': '.github/workflows/final-review.yml'},
            'workflow-4-runs': {'workflow_runs': []},
            'workflow-1-runs': {'workflow_runs': [run]}, 'workflow-2-runs': {'workflow_runs': []},
            'issues/7': {'user': {'login': 'owner'}, 'labels': []},
            'actions/runs/10/attempts/2/jobs?per_page=100&page=1': {'jobs': [
                {'name': 'gate', 'conclusion': 'success'}, {'name': 'claim', 'conclusion': 'success'},
                {'name': 'handoff', 'conclusion': 'failure'}, {'name': 'publish-reviews', 'conclusion': 'failure'},
                {'name': 'secret-model-text', 'conclusion': 'secret'}]},
            'actions/runs/10/artifacts?per_page=100&page=1': {'artifacts': [
                {'id': 100, 'name': 'feedback-2', 'expired': True}]},
            'pulls?state=all&head=owner:feat/7-implement&per_page=20': [],
            'issues/7/comments?per_page=100&page=1': [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, tools = root / 'candidate', root / 'tools'
            candidate.mkdir()
            tools.mkdir()
            for name in ('execution', 'json', 'control'):
                (candidate / f'{name}.py').write_text('raise RuntimeError("candidate import executed")\n')
            fixture = tools / 'fixtures.json'
            fixture.write_text(json.dumps(fixtures))
            gh = tools / 'gh'
            gh.write_text(f'#!{sys.executable} -I\n' + '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
path = next(arg for arg in args if arg.startswith('repos/')).split('/', 3)[3]
with open(os.environ['API_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if '--method' in args and args[args.index('--method') + 1] != 'GET':
    assert args[args.index('--method') + 1] == 'POST' and path == 'issues/7/comments'
    json.load(sys.stdin)
    print('{}')
else:
    if path.startswith('actions/workflows/1/runs?'): path = 'workflow-1-runs'
    if path.startswith('actions/workflows/2/runs?'): path = 'workflow-2-runs'
    if path.startswith('actions/workflows/4/runs?'): path = 'workflow-4-runs'
    print(json.dumps(json.loads(Path(os.environ['API_FIXTURE']).read_text())[path]))
''')
            gh.chmod(0o755)
            env = {**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                   'API_LOG': str(tools / 'calls.jsonl'), 'API_FIXTURE': str(fixture),
                   'GITHUB_REPOSITORY': repo, 'GITHUB_STEP_SUMMARY': str(root / 'summary')}
            result = subprocess.run([sys.executable, '-I', str(ROOT / 'observe.py'), '10', str(root / 'execution.json')],
                                    cwd=candidate, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads((root / 'execution.json').read_text())
            self.assertEqual(record['state'], 'failure')
            self.assertEqual(record['findings'], ['round-reviews-not-delivered'])
            self.assertEqual(record['jobs']['publish-reviews'], 'failure')
            self.assertIsNone(record['current_head'])
            self.assertIsNone(record['reviewed_head'])
            result = subprocess.run([sys.executable, '-I', str(ROOT / 'reconcile.py'), '--json'],
                                    cwd=candidate, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['runs'][0]['findings'], ['round-reviews-not-delivered', 'evidence-expired'])
            calls = [json.loads(line) for line in (tools / 'calls.jsonl').read_text().splitlines()]
            self.assertEqual(sum('POST' in args for args in calls), 1)
            self.assertFalse(any('/zip' in str(args) or '/logs' in str(args) for args in calls))
            self.assertNotIn('secret', json.dumps(record) + result.stdout)


if __name__ == '__main__':
    unittest.main()
