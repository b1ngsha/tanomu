import hashlib
import json
import os
from pathlib import Path
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
        "max_changed_lines": 10,
        "allowed_paths": ["src/a.ts", "src/new.ts", "dir with space/b.ts"],
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
