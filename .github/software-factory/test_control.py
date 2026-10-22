import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import control  # noqa: E402

CONTROL = Path(control.__file__).resolve()
OWNER = "owner"
REPO = f"{OWNER}/tanomu"
BODY = "Merge private messages.\n"
SECRET = "sk-test-0123456789abcdefghijklmnop"


class TaskDirectory(unittest.TestCase):
    """Points control.ROOT at a throwaway tasks/1.json."""

    spec = {
        "issue": 1,
        "body_sha256": hashlib.sha256(BODY.encode()).hexdigest(),
        "blocked_by": [2],
        "branch": "feat/1-thing",
        "title": "feat(core): add a thing",
        "max_changed_lines": 10,
        "allowed_paths": ["src/a.ts", "src/new.ts", "dir with space/b.ts"],
        "implement": "Build the thing.",
        "review": "Check the thing.",
        "acceptance": "Try the thing.",
    }

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / "tasks").mkdir()
        (self.root / "tasks" / "1.json").write_text(json.dumps(self.spec))
        self.enterContext(mock.patch.object(control, "ROOT", self.root))

    def assertRejects(self, reason, function, *args):
        with self.assertRaises(ValueError) as caught:
            function(*args)
        self.assertEqual(str(caught.exception), reason)


class TaskTest(TaskDirectory):
    def test_loads_matching_task(self):
        self.assertEqual(control.task("1")["branch"], "feat/1-thing")

    def test_rejects_malformed_numbers(self):
        for number in ("0", "01", "1/../1", "-1", "1 ", ""):
            with self.subTest(number=number):
                self.assertRejects("invalid-issue", control.task, number)

    def test_rejects_mismatched_issue(self):
        (self.root / "tasks" / "3.json").write_text(json.dumps({**self.spec, "issue": 4}))
        self.assertRejects("invalid-task", control.task, "3")

    def test_rejects_missing_task_text(self):
        for key in ("implement", "review", "acceptance"):
            for value in (None, " ", ["x"]):
                with self.subTest(key=key, value=value):
                    (self.root / "tasks" / "1.json").write_text(json.dumps({**self.spec, key: value}))
                    self.assertRejects("invalid-task", control.task, "1")

    def test_rejects_unconventional_titles(self):
        for title in (None, "add a thing", "feat: add a thing", "feat(core): a\nb",
                      "feat(core): " + "x" * 73, "Feat(core): add a thing"):
            with self.subTest(title=title):
                (self.root / "tasks" / "1.json").write_text(json.dumps({**self.spec, "title": title}))
                self.assertRejects("invalid-title", control.task, "1")

    def test_prompt_appends_task_requirements(self):
        (self.root / "prompts").mkdir()
        (self.root / "prompts" / "review.md").write_text("Generic review.\n")
        self.assertEqual(control.prompt("review", "1"),
                         "Generic review.\n\nTask-specific requirements:\nCheck the thing.\n")
        self.assertRejects("invalid-mode", control.prompt, "acceptance", "1")

    def test_real_tasks_are_valid(self):
        for path in (CONTROL.parent / "tasks").glob("*.json"):
            with self.subTest(task=path.name), mock.patch.object(control, "ROOT", CONTROL.parent):
                control.task(path.stem)


class ScopeTest(TaskDirectory):
    def setUp(self):
        super().setUp()
        self.repo = Path(self.enterContext(tempfile.TemporaryDirectory()))
        cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)
        self.run_git("init", "-q", "-b", "main")
        self.run_git("config", "user.email", "factory@example.com")
        self.run_git("config", "user.name", "factory")
        self.run_git("config", "core.autocrlf", "false")
        self.write("src/a.ts", "one\ntwo\n")
        self.write("README.md", "readme\n")
        self.run_git("add", "--all")
        self.run_git("commit", "-q", "-m", "base")
        self.base = self.run_git("rev-parse", "HEAD").strip()

    def run_git(self, *args):
        return subprocess.check_output(["git", *args], text=True)

    def write(self, name, content):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)
        return path

    def scope(self):
        control.scope("1", self.base)

    def test_accepts_allowed_modification(self):
        self.write("src/a.ts", "one\nthree\n")
        self.scope()

    def test_accepts_untracked_allowed_file(self):
        self.write("src/new.ts", "export const x = 1;\n")
        self.scope()

    def test_accepts_staged_and_intent_to_add_files(self):
        self.write("src/new.ts", "export const x = 1;\n")
        self.run_git("add", "--intent-to-add", "src/new.ts")
        self.write("src/a.ts", "one\nthree\n")
        self.run_git("add", "src/a.ts")
        self.scope()

    def test_accepts_quoted_path(self):
        self.write("dir with space/b.ts", "b\n")
        self.scope()

    def test_does_not_modify_real_index(self):
        self.write("src/new.ts", "x\n")
        before = self.run_git("status", "--porcelain")
        self.scope()
        self.assertEqual(self.run_git("status", "--porcelain"), before)
        self.assertIn("?? src/new.ts", before)

    def test_rejects_empty_patch(self):
        self.assertRejects("empty-patch", self.scope)

    def test_rejects_untracked_file_outside_allowlist(self):
        self.write("src/a.ts", "one\nthree\n")
        self.write(".github/workflows/evil.yml", "on: push\n")
        self.assertRejects("path-outside-allowlist", self.scope)

    def test_rejects_staged_file_outside_allowlist(self):
        self.write("src/a.ts", "one\nthree\n")
        self.write("package.json", "{}\n")
        self.run_git("add", "package.json")
        self.assertRejects("path-outside-allowlist", self.scope)

    def test_rejects_intent_to_add_file_outside_allowlist(self):
        self.write("src/a.ts", "one\nthree\n")
        self.write("src/other.ts", "x\n")
        self.run_git("add", "--intent-to-add", "src/other.ts")
        self.assertRejects("path-outside-allowlist", self.scope)

    def test_rejects_path_prefix_and_traversal_lookalikes(self):
        for name in ("src/a.ts.bak", "src/new.ts/inner", "x/../src/z.ts"):
            with self.subTest(name=name):
                self.write(name, "x\n")
                self.assertRejects("path-outside-allowlist", self.scope)
                self.run_git("clean", "-qfdx")

    def test_rejects_deleting_allowed_file(self):
        (self.repo / "src/a.ts").unlink()
        self.assertRejects("invalid-file-type", self.scope)

    def test_rejects_deleting_file_outside_allowlist(self):
        (self.repo / "README.md").unlink()
        self.assertRejects("path-outside-allowlist", self.scope)

    def test_rejects_untracked_symlink(self):
        os.symlink("/etc/passwd", self.repo / "src/new.ts")
        self.assertRejects("invalid-file-type", self.scope)

    def test_rejects_replacing_file_with_symlink(self):
        (self.repo / "src/a.ts").unlink()
        os.symlink("../README.md", self.repo / "src/a.ts")
        self.assertRejects("invalid-file-type", self.scope)

    def test_rejects_executable_mode(self):
        os.chmod(self.repo / "src/a.ts", 0o755)
        self.assertRejects("invalid-file-type", self.scope)

    def test_rejects_new_executable_file(self):
        os.chmod(self.write("src/new.ts", "x\n"), 0o755)
        self.assertRejects("invalid-file-type", self.scope)

    def test_rejects_binary_file(self):
        self.write("src/new.ts", b"\x00\x01\x02binary")
        self.assertRejects("binary-patch", self.scope)

    def test_rejects_patch_over_line_limit(self):
        self.write("src/new.ts", "x\n" * 11)
        self.assertRejects("patch-too-large", self.scope)

    def test_accepts_patch_at_line_limit(self):
        # 2 removed + 8 added == 10.
        self.write("src/a.ts", "x\n" * 8)
        self.scope()

    def test_line_limit_counts_untracked_files(self):
        self.write("src/a.ts", "one\nthree\n")
        self.write("src/new.ts", "x\n" * 9)
        self.assertRejects("patch-too-large", self.scope)

    def test_rejects_whitespace_errors(self):
        self.write("src/a.ts", "one\ntwo  \n")
        self.assertRejects("whitespace-error", self.scope)

    def test_rejects_invalid_base(self):
        self.write("src/a.ts", "one\nthree\n")
        for base in ("--output=/tmp/x", "does-not-exist", "0" * 40):
            with self.subTest(base=base):
                self.assertRejects("invalid-base", control.scope, "1", base)

    def test_accepts_symbolic_base(self):
        self.write("src/a.ts", "one\nthree\n")
        control.scope("1", "main")


def issue(**overrides):
    value = {"state": "open", "user": {"login": OWNER}, "body": BODY,
             "labels": [{"name": "ready-for-agent"}, {"name": "agent:implement"}]}
    value.update(overrides)
    return value


def labeled(event, actor, name="agent:implement"):
    return {"event": event, "actor": {"login": actor}, "label": {"name": name}}


class GateTest(TaskDirectory):
    def setUp(self):
        super().setUp()
        self.out = Path(self.enterContext(tempfile.TemporaryDirectory())) / "input"
        self.enterContext(mock.patch.dict(os.environ, {
            "GITHUB_REF": "refs/heads/main", "MODEL": control.MODEL, "GITHUB_REPOSITORY": REPO,
            "GITHUB_ACTOR": OWNER, "GITHUB_TRIGGERING_ACTOR": OWNER,
        }))
        self.issue = issue()
        self.dependency = {"state": "closed", "state_reason": "completed"}
        self.refs = []
        self.pulls = []
        self.pages = [[labeled("labeled", "intruder"), labeled("unlabeled", OWNER)],
                      [labeled("labeled", "intruder", "ready-for-agent"),
                       labeled("labeled", OWNER), {"event": "commented"}]]
        self.calls = []
        self.enterContext(mock.patch.object(control, "api", self.fake_api))
        self.enterContext(mock.patch.object(control.subprocess, "check_output", self.fake_events))

    def fake_api(self, path):
        self.calls.append(path)
        return {
            f"repos/{REPO}/issues/1": self.issue,
            f"repos/{REPO}/issues/2": self.dependency,
            f"repos/{REPO}/git/matching-refs/heads/feat/1-thing": self.refs,
            f"repos/{REPO}/pulls?state=all&head={OWNER}:feat/1-thing": self.pulls,
        }[path]

    def fake_events(self, command):
        self.assertEqual(command, ["gh", "api", "--paginate", "--slurp",
                                   f"repos/{REPO}/issues/1/events?per_page=100"])
        return json.dumps(self.pages).encode()

    def gate(self):
        control.gate("1", str(self.out))

    def test_accepts_authorized_issue_and_writes_body(self):
        self.gate()
        self.assertEqual((self.out / "issue.md").read_text(), BODY)
        self.assertIn(f"repos/{REPO}/issues/2", self.calls)

    def test_rejects_environment(self):
        for key, value, reason in (
            ("GITHUB_REF", "refs/heads/feature", "wrong-ref"),
            ("GITHUB_REF", "refs/pull/1/merge", "wrong-ref"),
            ("MODEL", "opencode/other", "unsupported-model"),
            ("GITHUB_ACTOR", "intruder", "wrong-actor"),
            ("GITHUB_TRIGGERING_ACTOR", "intruder", "wrong-triggering-actor"),
        ):
            with self.subTest(key=key, value=value), mock.patch.dict(os.environ, {key: value}):
                self.assertRejects(reason, self.gate)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.out.exists())

    def test_rejects_issue_state_and_author(self):
        for overrides, reason in (
            ({"state": "closed"}, "not-open-issue"),
            ({"pull_request": {}}, "not-open-issue"),
            ({"user": {"login": "intruder"}}, "wrong-author"),
            ({"labels": [{"name": "agent:implement"}]}, "missing-authorization"),
            ({"labels": [{"name": "ready-for-agent"}]}, "missing-authorization"),
            ({"labels": [{"name": "ready-for-agent"}, {"name": "agent:implement"},
                         {"name": "implementing"}]}, "already-claimed"),
            ({"labels": [{"name": "ready-for-agent"}, {"name": "agent:implement"},
                         {"name": "needs-human"}]}, "already-claimed"),
        ):
            with self.subTest(reason=reason, overrides=overrides):
                self.issue = issue(**overrides)
                self.assertRejects(reason, self.gate)
        self.assertFalse(self.out.exists())

    def test_rejects_label_from_non_owner(self):
        self.pages = [[labeled("labeled", OWNER)], [labeled("labeled", "intruder")]]
        self.assertRejects("wrong-label-actor", self.gate)

    def test_rejects_label_without_event_history(self):
        self.pages = [[labeled("labeled", OWNER, "ready-for-agent")]]
        self.assertRejects("wrong-label-actor", self.gate)

    def test_rejects_owner_label_later_removed(self):
        self.pages = [[labeled("labeled", OWNER), labeled("unlabeled", OWNER)]]
        self.assertRejects("wrong-label-actor", self.gate)

    def test_rejects_changed_or_missing_body(self):
        for body in (BODY + "Also deploy to production.\n", None, ""):
            with self.subTest(body=body):
                self.issue = issue(body=body)
                self.assertRejects("body-changed", self.gate)
        self.assertFalse(self.out.exists())

    def test_rejects_unfinished_dependency(self):
        for dependency in ({"state": "open", "state_reason": None},
                           {"state": "closed", "state_reason": "not_planned"},
                           {"state": "closed", "state_reason": "duplicate"},
                           {"state": "closed"}):
            with self.subTest(dependency=dependency):
                self.dependency = dependency
                self.assertRejects("open-dependency", self.gate)

    def test_rejects_existing_branch(self):
        self.refs = [{"ref": "refs/heads/feat/1-thing"}]
        self.assertRejects("branch-exists", self.gate)

    def test_ignores_branch_prefix_matches(self):
        self.refs = [{"ref": "refs/heads/feat/1-thing-old"}]
        self.gate()

    def test_rejects_existing_pull_request(self):
        self.pulls = [{"number": 9}]
        self.assertRejects("pr-exists", self.gate)


class ClaimedTest(GateTest):
    def setUp(self):
        super().setUp()
        self.issue["labels"] = [{"name": name} for name in ("ready-for-agent", "implementing")]
        self.event = {**labeled("labeled", "github-actions[bot]", "implementing"), "id": 987}
        self.pages = [[labeled("labeled", OWNER)], [self.event]]
        self.enterContext(mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}))
        self.record = self.root / "claim.json"

    # GateTest's cases also exercise the shared validation against claimed state.
    def gate(self):
        control.validate_issue("1", claimed=True)

    def test_accepts_authorized_issue_and_writes_body(self):
        control.record_claim("1", str(self.record))
        control.claimed("1", str(self.record))
        record = json.loads(self.record.read_text())
        self.assertEqual(record, {"issue": "1", "repository": REPO, "run_id": "123",
                                  "run_attempt": "1", "event_id": 987})

    def test_rejects_label_without_event_history(self):
        self.pages = [[labeled("labeled", OWNER)]]
        self.assertRejects("wrong-label-actor", self.gate)

    def test_rejects_label_from_non_owner(self):
        self.event["actor"]["login"] = OWNER
        self.assertRejects("wrong-label-actor", self.gate)

    def test_rejects_owner_label_later_removed(self):
        self.pages[-1].append(labeled("unlabeled", "github-actions[bot]", "implementing"))
        self.assertRejects("wrong-label-actor", self.gate)

    def test_rejects_issue_state_and_author(self):
        for labels in (("ready-for-agent",), ("implementing",),
                       ("ready-for-agent", "implementing", "agent:implement"),
                       ("ready-for-agent", "implementing", "needs-human"),
                       ("ready-for-agent", "implementing", "ready-for-human")):
            with self.subTest(labels=labels):
                self.issue["labels"] = [{"name": name} for name in labels]
                reason = "missing-authorization" if len(labels) == 1 else "already-claimed"
                self.assertRejects(reason, self.gate)

    def test_rejects_changed_or_missing_body(self):
        for body in (BODY + "changed", None, ""):
            with self.subTest(body=body):
                self.issue["body"] = body
                self.assertRejects("body-changed", self.gate)

    def test_rejects_stale_run_attempt_repository_issue_and_event(self):
        control.record_claim("1", str(self.record))
        original = self.record.read_text()
        for key, value in (("run_id", "999"), ("run_attempt", "2"), ("repository", "other/repo"),
                           ("issue", "2"), ("event_id", 988)):
            with self.subTest(key=key):
                data = json.loads(original)
                data[key] = value
                self.record.write_text(json.dumps(data))
                self.assertRejects("stale-claim", control.claimed, "1", str(self.record))
        self.record.write_text(original)
        self.event["id"] = 989
        self.assertRejects("stale-claim", control.claimed, "1", str(self.record))

    def test_rejects_claim_event_without_valid_id(self):
        for value in (None, "987", True, 0):
            with self.subTest(value=value):
                self.event["id"] = value
                self.assertRejects("invalid-claim-event", control.record_claim, "1", str(self.record))
        self.assertFalse(self.record.exists())


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.auth = self.directory / "auth.json"
        self.auth.write_text(json.dumps({"opencode": {"type": "api", "key": "Zq9/\"opaque+cred",
                                                       "short": "abc"}}))
        self.enterContext(mock.patch.dict(os.environ, {"FACTORY_AUTH_FILE": str(self.auth)}))

    def artifact(self, content):
        path = self.directory / "artifact"
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        return str(path)

    def assertRejects(self, reason, content):
        with self.assertRaises(ValueError) as caught:
            control.scan(self.artifact(content))
        self.assertEqual(str(caught.exception), reason)

    def test_accepts_clean_artifact(self):
        control.scan(self.artifact("diff --git a/x b/x\n+const task-assessment-for-merged-private = 1\n"
                                   "+// abc api key handling\n"))

    def test_accepts_without_auth_file(self):
        with mock.patch.dict(os.environ):
            del os.environ["FACTORY_AUTH_FILE"]
            with self.assertRaisesRegex(ValueError, "^missing-auth-file$"):
                control.scan(self.artifact("Zq9/\"opaque+cred"))
            control.scan(self.artifact("Zq9/\"opaque+cred"), public=True)
            with self.assertRaisesRegex(ValueError, "^credential-pattern-in-artifact$"):
                control.scan(self.artifact(SECRET), public=True)

    def test_rejects_exact_credential(self):
        self.assertRejects("credential-in-artifact", 'leak Zq9/"opaque+cred here')

    def test_rejects_json_escaped_credential(self):
        event = json.dumps({"type": "text", "part": {"text": 'Zq9/"opaque+cred'}})
        self.assertRejects("credential-in-artifact", event)

    def test_ignores_short_values(self):
        control.scan(self.artifact("abc api"))

    def test_rejects_credential_patterns(self):
        for content in ("ghp_" + "a" * 36, "token=gho_" + "B" * 20, "github_pat_" + "c_" * 15,
                        SECRET, "(sk-" + "d" * 20 + ")",
                        "-----BEGIN OPENSSH PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----"):
            with self.subTest(content=content[:12]):
                self.assertRejects("credential-pattern-in-artifact", content)

    def test_rejects_oversized_artifact(self):
        self.assertRejects("artifact-too-large", b"a" * (control.MAX_ARTIFACT_BYTES + 1))

    def test_accepts_artifact_at_size_limit(self):
        control.scan(self.artifact(b"a" * control.MAX_ARTIFACT_BYTES))

    def test_cli_failure_does_not_expose_credential(self):
        for content, reason in ((f"x {SECRET}", "credential-pattern-in-artifact"),
                                ('Zq9/"opaque+cred', "credential-in-artifact")):
            with self.subTest(reason=reason):
                result = subprocess.run([sys.executable, "-I", str(CONTROL), "scan", self.artifact(content)],
                                        capture_output=True, text=True, env={**os.environ})
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, f"::error::{reason}\n")

    def test_cli_hides_unexpected_error_details(self):
        self.auth.write_text(f"not json {SECRET}")
        result = subprocess.run([sys.executable, "-I", str(CONTROL), "scan", self.artifact("ok")],
                                capture_output=True, text=True, env={**os.environ})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "::error::control-failed\n")
        self.assertNotIn(SECRET, result.stdout + result.stderr)


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def events(self, *texts, extra=()):
        path = self.directory / "events.jsonl"
        lines = [json.dumps({"type": "step_start"})]
        lines += [json.dumps({"type": "text", "part": {"text": text}}) for text in texts]
        lines += [json.dumps(event) for event in extra]
        path.write_text("\n".join(lines) + "\n")
        return str(path)

    def assertRejects(self, reason, filename):
        with self.assertRaises(ValueError) as caught:
            control.review(filename)
        self.assertEqual(str(caught.exception), reason)

    def test_accepts_approval(self):
        self.assertEqual(control.review(self.events('{"verdict":"approve",', '"findings":[]}')),
                         {"verdict": "approve", "findings": []})

    def test_accepts_request_changes(self):
        result = control.review(self.events(json.dumps(
            {"verdict": "request_changes", "findings": ["src/a.ts: fix timer reset"]})))
        self.assertEqual(result["findings"], ["src/a.ts: fix timer reset"])

    def test_rejects_error_events(self):
        for event in ({"type": "error"}, {"type": "step_finish", "error": {"message": "boom"}}):
            with self.subTest(event=event):
                self.assertRejects("invalid-events",
                                   self.events('{"verdict":"approve","findings":[]}', extra=[event]))

    def test_rejects_non_object_events(self):
        path = self.directory / "list.jsonl"
        path.write_text('["type", "text"]\n')
        self.assertRejects("invalid-events", str(path))
        path.write_text("")
        self.assertRejects("invalid-events", str(path))

    def test_rejects_malformed_schema(self):
        for text, reason in (
            ("Looks good!", "invalid-review"),
            ('```json\n{"verdict":"approve","findings":[]}\n```', "invalid-review"),
            ('["verdict", "findings"]', "invalid-review"),
            ('{"verdict":"approve"}', "invalid-review"),
            ('{"verdict":"approve","findings":[],"extra":1}', "invalid-review"),
            ('{"verdict":"request_changes","findings":["x"],"verdict":"approve","findings":[]}',
             "invalid-review"),
            ('{"verdict":"APPROVE","findings":[]}', "invalid-verdict"),
            ('{"verdict":["approve"],"findings":[]}', "invalid-verdict"),
            ('{"verdict":"request_changes","findings":"x"}', "invalid-findings"),
            ('{"verdict":"request_changes","findings":[1]}', "invalid-findings"),
            ('{"verdict":"request_changes","findings":["  "]}', "invalid-findings"),
            (json.dumps({"verdict": "request_changes", "findings": ["x" * 2001]}), "invalid-findings"),
            (json.dumps({"verdict": "request_changes", "findings": ["x"] * 21}), "invalid-findings"),
            ('{"verdict":"approve","findings":["x"]}', "inconsistent-review"),
            ('{"verdict":"request_changes","findings":[]}', "inconsistent-review"),
        ):
            with self.subTest(text=text[:60]):
                self.assertRejects(reason, self.events(text))

    def test_accepts_limits(self):
        control.review(self.events(json.dumps(
            {"verdict": "request_changes", "findings": ["x" * 2000] * 20})))


class EventsTest(unittest.TestCase):
    def test_rejects_unparseable_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text('{"type":"text"}\nnot json\n')
            with self.assertRaisesRegex(ValueError, "^invalid-events$"):
                control.events(str(path))
            path.write_text('{"type":"step_start"}\n{"type":"text","part":{"text":"done"}}\n')
            self.assertEqual(len(control.events(str(path))), 2)


class DiagnoseTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.log = self.directory / "checks.log"
        self.output = self.directory / "checks.json"

    def test_keeps_bounded_tail_without_ansi(self):
        self.log.write_bytes(b"x" * control.MAX_DIAGNOSTIC_BYTES + b"\x1b[31mFAIL\x1b[0m a.test.ts\xff")
        control.diagnose(str(self.output), "pnpm test", str(self.log))
        result = json.loads(self.output.read_text())
        self.assertEqual(result["command"], "pnpm test")
        self.assertTrue(result["output"].endswith("FAIL a.test.ts�"))
        self.assertNotIn("\x1b", result["output"])
        self.assertLessEqual(len(result["output"].encode()), control.MAX_DIAGNOSTIC_BYTES + 3)

    def test_rejects_unknown_command(self):
        self.log.write_text("boom")
        with self.assertRaisesRegex(ValueError, "^invalid-check$"):
            control.diagnose(str(self.output), "rm -rf /", str(self.log))


LEAKY_EVENTS = [
    {"type": "step_start", "timestamp": 1_700_000_001_000},
    {"type": "text", "part": {"text": SECRET}},
    {"type": "tool_use", "part": {"tool": "read", "state": {
        "status": "completed", "input": {"filePath": "/home/runner/.env"}, "output": SECRET}}},
    {"type": "tool_use", "part": {"tool": "edit", "state": {
        "status": "error", "error": f"permission denied {SECRET}"}}},
    {"type": "tool_use", "part": {"tool": "edit", "state": {"status": "error"}}},
    {"type": "tool_use", "part": {"tool": f"mcp_{SECRET}", "state": {"status": SECRET}}},
    {"type": "step_finish", "timestamp": 1_700_000_031_000,
     "part": {"reason": "tool-calls", "tokens": {"input": 10, "output": 5, "reasoning": "x"}}},
    {"type": f"leak_{SECRET}", "error": {"name": SECRET}},
]


class SummaryTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "events.jsonl"

    def test_counts_only_allowlisted_categories(self):
        self.path.write_text("\n".join(map(json.dumps, LEAKY_EVENTS)) + "\nnot json\n[1]\n")
        result = control.summarize(str(self.path), "124", "600", "1700000000")
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn("/home", json.dumps(result))
        self.assertEqual(result["exit_status"], 124)
        self.assertEqual((result["events"], result["malformed"]), (8, 2))
        self.assertEqual(result["event_types"],
                         {"step_start": 1, "text": 1, "tool_use": 4, "step_finish": 1, "other": 1})
        self.assertEqual(result["tools"], {"read": {"completed": 1}, "edit": {"error": 2},
                                           "other": {"other": 1}})
        self.assertEqual(result["longest_same_tool_streak"], 2)
        self.assertEqual(result["finish_reasons"], {"tool-calls": 1})
        self.assertEqual(result["tokens"], {"input": 10, "output": 5, "reasoning": 0})
        self.assertEqual(result["last_event_after_seconds"], 31)

    def test_bounds_lines_and_tolerates_missing_file(self):
        with mock.patch.object(control, "MAX_EVENT_LINE_BYTES", 64):
            self.path.write_text('{"type":"text","part":{"text":"' + "x" * 300 + '"}}\n{"type":"text"}\n')
            result = control.summarize(str(self.path), "0", "1", "0")
        self.assertEqual((result["events"], result["oversized"]), (1, 1))
        missing = control.summarize(str(self.path) + ".missing", "1", "2", "0")
        self.assertEqual((missing["events"], missing["last_event_after_seconds"]), (0, None))

    def test_unhashable_fields_count_as_other(self):
        self.path.write_text(json.dumps({"type": ["tool_use"]}) + "\n" + json.dumps(
            {"type": "tool_use", "part": {"tool": {"x": 1}, "state": {"status": [1]}}}) + "\n" + json.dumps(
            {"type": "step_finish", "part": {"reason": {"x": 1}, "tokens": []}}) + "\n")
        result = control.summarize(str(self.path), "0", "1", "0")
        self.assertEqual(result["event_types"], {"other": 1, "tool_use": 1, "step_finish": 1})
        self.assertEqual(result["tools"], {"other": {"other": 1}})
        self.assertEqual(result["finish_reasons"], {"other": 1})

    def test_total_bytes_cap_covers_unterminated_line(self):
        with mock.patch.object(control, "MAX_EVENT_LINE_BYTES", 64), \
                mock.patch.object(control, "MAX_EVENT_BYTES", 1000):
            self.path.write_text('{"type":"text"}\n' + "x" * 100_000)
            result = control.summarize(str(self.path), "0", "1", "0")
        self.assertEqual((result["events"], result["oversized"], result["truncated"]), (1, 1, True))

    def test_rejects_non_numeric_inputs(self):
        self.path.write_text("")
        for args in (("x", "1", "0"), ("1", "-1", "0"), ("1", "1", "0;rm")):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "^invalid-summary-input$"):
                control.summarize(str(self.path), *args)


class RunnerStepTest(unittest.TestCase):
    """Runs the real OpenCode step scripts against stub `opencode` and `timeout` binaries."""

    def run_step(self, job, opencode):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (directory / "trusted").symlink_to(CONTROL.parents[2])
        (directory / "candidate").mkdir()
        bin_dir = directory / "bin"
        bin_dir.mkdir()
        # A real deadline shortened to one second; exit 124 mirrors coreutils timeout.
        (bin_dir / "timeout").write_text(
            f"#!{sys.executable}\nimport subprocess, sys\nargs = sys.argv[1:]\n"
            "while args[0].startswith('-'): args.pop(0)\n"
            "try: sys.exit(subprocess.run(args[1:], timeout=1).returncode)\n"
            "except subprocess.TimeoutExpired: sys.exit(124)\n")
        (bin_dir / "opencode").write_text(f"#!/bin/sh\n{opencode}\n")
        for stub in bin_dir.iterdir():
            stub.chmod(0o755)
        auth = directory / "auth.json"
        auth.write_text(json.dumps({"key": SECRET}))
        (directory / "temp").mkdir()
        step = next(step for step in WorkflowContractTest.load("software-factory-round.yml")["jobs"][job]["steps"]
                    if "opencode run" in step.get("run", ""))
        env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "MODEL": control.MODEL, "ISSUE": "6",
               "RUNNER_TEMP": str(directory / "temp"), "FACTORY_AUTH_FILE": str(auth),
               "GITHUB_OUTPUT": str(directory / "output"), "GITHUB_STEP_SUMMARY": str(directory / "summary"),
               "REVIEW_OUTPUT": str(directory / "temp/feedback/review.json")}
        result = subprocess.run(["bash", "-e", "-c", step["run"]], cwd=directory / "candidate", env=env,
                                capture_output=True, text=True, timeout=30)
        return result, (directory / "summary").read_text() if (directory / "summary").exists() else ""

    def stub_events(self, *events):
        return "\n".join(f"echo '{json.dumps(event)}'" for event in events)

    def test_timeout_is_summarized_and_preserved_without_leaking(self):
        leaky = [event for event in LEAKY_EVENTS if "'" not in json.dumps(event)]
        for job in ("implement", "review"):
            with self.subTest(job=job):
                result, summary = self.run_step(job, self.stub_events(*leaky) + f"\necho {SECRET} >&2\nexec sleep 20")
                self.assertEqual(result.returncode, 124, result.stderr)
                self.assertIn('"exit_status": 124', result.stdout)
                self.assertIn('"tool_use": 4', summary)
                self.assertIn("::error::opencode-exit-124", result.stdout)
                self.assertNotIn(SECRET, result.stdout + result.stderr + summary)

    def test_nonzero_exit_is_preserved(self):
        result, _ = self.run_step("implement", self.stub_events({"type": "step_start"}) + "\nexit 3")
        self.assertEqual(result.returncode, 3)
        self.assertIn('"exit_status": 3', result.stdout)

    def test_success_still_validates_events(self):
        result, _ = self.run_step("implement", self.stub_events({"type": "text"}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"exit_status": 0', result.stdout)
        result, _ = self.run_step("implement", self.stub_events({"type": "error"}))
        self.assertEqual(result.returncode, 1)
        self.assertIn("::error::invalid-events", result.stderr)
        review = {"verdict": "approve", "findings": []}
        result, _ = self.run_step("review", self.stub_events(
            {"type": "text", "part": {"text": json.dumps(review)}}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"exit_status": 0', result.stdout)


class WorkflowContractTest(unittest.TestCase):
    """Wiring between jobs is not exercised by the unit tests above, so pin its invariants."""

    @staticmethod
    def load(name):
        import yaml
        return yaml.safe_load((CONTROL.parents[2] / ".github/workflows" / name).read_text())

    def setUp(self):
        self.implement = self.load("software-factory-implement.yml")
        self.round = self.load("software-factory-round.yml")

    def steps(self):
        for workflow in (self.implement, self.round):
            for job in workflow["jobs"].values():
                yield from job.get("steps", [])

    def test_issue_validation_steps_receive_model(self):
        validating = [step for step in self.steps()
                      if re.search(r"control\.py (gate|record-claim|claimed) ", step.get("run", ""))]
        self.assertEqual(len(validating), 4)
        for step in validating:
            with self.subTest(step=step.get("name")):
                self.assertIn("MODEL", step.get("env", {}))

    def test_repairable_outcomes_reach_every_later_round(self):
        jobs = self.implement["jobs"]
        rounds = sorted(name for name in jobs if name.startswith("round"))
        self.assertEqual(rounds, ["round1", "round2", "round3", "round4"])
        for previous, current in zip(rounds, rounds[1:]):
            with self.subTest(round=current):
                self.assertEqual(jobs[current]["needs"], previous)
                for outcome in ("checks_failed", "request_changes"):
                    self.assertIn(f"needs.{previous}.outputs.outcome == '{outcome}'", jobs[current]["if"])
        for job in ("handoff", "report"):
            self.assertLessEqual(set(rounds), set(jobs[job]["needs"]))
        self.assertIn("needs.round4.outputs.outcome", str(jobs["report"]))

    def test_checked_patch_is_uploaded_before_candidate_code_runs(self):
        steps = self.round["jobs"]["verify"]["steps"]
        upload = next(index for index, step in enumerate(steps)
                      if step.get("with", {}).get("name") == "checked-${{ inputs.round }}")
        for index, step in enumerate(steps):
            if re.search(r"pnpm (lint|typecheck|build:admin|test)", step.get("run", "")):
                self.assertGreater(index, upload, step["run"])
        self.assertNotIn("secrets", str(self.round["jobs"]["verify"]))

    def test_shared_files_contain_no_task_specific_text(self):
        task = json.loads((CONTROL.parent / "tasks" / "6.json").read_text())
        shared = [CONTROL.parent / "prompts" / "implement.md", CONTROL.parent / "prompts" / "review.md",
                  *(CONTROL.parents[2] / ".github/workflows").glob("software-factory-*.yml")]
        for path in shared:
            text = path.read_text()
            for fragment in (task["title"], "2.5", "batch"):
                with self.subTest(path=path.name, fragment=fragment):
                    self.assertNotIn(fragment, text)

    def test_review_repair_and_handoff_use_the_checked_patch(self):
        def downloads(job):
            return {step["with"]["name"] for step in job["steps"]
                    if "download-artifact" in step.get("uses", "")}
        jobs = self.round["jobs"]
        self.assertEqual(downloads(jobs["review"]), {"factory-input", "checked-${{ inputs.round }}"})
        self.assertEqual(downloads(jobs["implement"]), {
            "factory-input", "checked-${{ steps.previous.outputs.round }}",
            "feedback-${{ steps.previous.outputs.round }}"})
        self.assertEqual(downloads(self.implement["jobs"]["handoff"]),
                         {"checked-${{ steps.approved.outputs.round }}", "factory-claim"})


class ConfigureTest(TaskDirectory):
    denied = ("external_directory", "bash", "webfetch", "websearch", "task", "skill")

    def setUp(self):
        super().setUp()
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.workspace = self.directory / "workspace"
        self.workspace.mkdir()
        self.github_env = self.directory / "github_env"
        self.enterContext(mock.patch.dict(os.environ, {
            "OPENCODE_AUTH_JSON": json.dumps({"k": SECRET}), "GITHUB_ENV": str(self.github_env),
            "FACTORY_WORKSPACE": str(self.workspace), "FACTORY_ISSUE": "1"}))

    def configure(self, mode):
        control.configure(str(self.directory / "oc"), mode)
        return json.loads((self.directory / "oc/opencode.json").read_text())

    def test_review_is_read_only(self):
        config = self.configure("review")
        self.assertFalse(config["share"])
        self.assertEqual(config["permission"]["read"], {
            "*": "allow", ".env": "deny", ".env.*": "deny", "**/.env": "deny",
            "**/.env.*": "deny", "**/auth.json": "deny"})
        self.assertEqual(config["permission"]["*"], "deny")
        self.assertEqual(config["permission"]["edit"], "deny")
        for tool in self.denied:
            self.assertEqual(config["permission"][tool], "deny")

    def test_implement_edits_only_allowed_paths(self):
        names = ["src/a.ts", "packages/core/test/b.test.ts"]
        (self.root / "tasks" / "1.json").write_text(json.dumps({**self.spec, "allowed_paths": names}))
        permission = self.configure("implement")["permission"]
        self.assertEqual(permission["edit"], {"*": "deny", **{name: "allow" for name in names}})
        # Last match wins in OpenCode, so the catch-all deny must precede the allows.
        self.assertEqual(list(permission["edit"]), ["*", *names])
        self.assertFalse(any(key.startswith("/") for key in permission["edit"]))
        for tool in self.denied:
            self.assertEqual(permission[tool], "deny")

    def test_rejects_unsafe_allowed_paths(self):
        for name in ("../outside.ts", "/etc/passwd", ".git/config", "src/../.git/hooks/pre-commit",
                     "src/*.ts", "a\nb", "src/../../x.ts"):
            with self.subTest(name=name):
                (self.root / "tasks" / "1.json").write_text(json.dumps({**self.spec, "allowed_paths": [name]}))
                self.assertRejects("invalid-allowed-path", self.configure, "implement")
        self.assertFalse((self.directory / "oc/data/opencode/auth.json").exists())

    def test_rejects_unknown_mode(self):
        self.assertRejects("invalid-mode", self.configure, "admin")
        self.assertFalse((self.directory / "oc/data/opencode/auth.json").exists())

    def test_auth_is_private_even_if_existing(self):
        auth = self.directory / "oc/data/opencode/auth.json"
        auth.parent.mkdir(parents=True)
        auth.write_text("stale")
        auth.chmod(0o644)
        self.configure("review")
        self.assertEqual(auth.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(auth.read_text()), {"k": SECRET})
        self.assertIn(f"FACTORY_AUTH_FILE={auth}\n", self.github_env.read_text())
        self.assertNotIn(SECRET, self.github_env.read_text())


if __name__ == "__main__":
    unittest.main()
