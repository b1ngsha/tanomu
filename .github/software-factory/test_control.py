import hashlib
import json
import os
from pathlib import Path
import re
import shutil
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

    def real_prompts(self):
        for name in ("prompts", "skills"):
            shutil.copytree(CONTROL.parent / name, self.root / name)

    def test_implement_prompt_appends_task_requirements(self):
        self.real_prompts()
        text = control.prompt("implement", "1")
        self.assertTrue(text.startswith((CONTROL.parent / "prompts/implement.md").read_text()))
        self.assertTrue(text.endswith("\nTask-specific requirements:\nBuild the thing.\n"))

    def test_review_axes_get_separate_briefs(self):
        self.real_prompts()
        standards = control.prompt("review-standards", "1")
        spec = control.prompt("review-spec", "1")
        axes = control.review_axes()
        for text, axis, other in ((standards, "standards", "spec"), (spec, "spec", "standards")):
            with self.subTest(axis=axis):
                self.assertIn(f"You are the {axis.title()} sub-agent", text)
                self.assertIn(f"Brief: {axes[axis]['brief']}", text)
                self.assertIn(axes[axis]["blocking"], text)
                self.assertNotIn(axes[other]["brief"], text)
                self.assertNotIn("AXIS", text)
                self.assertNotIn("BLOCKING", text)
        # Only Standards carries the smell baseline; only Spec carries the task's requirements.
        self.assertIn("**Feature Envy**", standards)
        self.assertNotIn("**Feature Envy**", spec)
        self.assertIn("Task-specific review requirements:\nCheck the thing.", spec)
        self.assertNotIn("Check the thing.", standards)


    def test_rejects_unknown_prompt_modes(self):
        self.real_prompts()
        for mode in ("acceptance", "review", "review-", "review-security"):
            with self.subTest(mode=mode):
                self.assertRejects("invalid-mode", control.prompt, mode, "1")

    def test_rejects_changed_review_skill(self):
        self.real_prompts()
        path = self.root / "skills/code-review/SKILL.md"
        original = path.read_text()
        for old, new in (("- The brief: ", "- Brief: "),
                         ("### 3. Identify the standards sources", "### 3. Standards")):
            with self.subTest(old=old):
                path.write_text(original.replace(old, new, 1))
                self.assertRejects("skill-changed", control.prompt, "review-standards", "1")

    def test_real_tasks_are_valid(self):
        for path in (CONTROL.parent / "tasks").glob("*.json"):
            with self.subTest(task=path.name), mock.patch.object(control, "ROOT", CONTROL.parent):
                control.task(path.stem)


class SkillPinTest(unittest.TestCase):
    """The vendored skills are trusted prompt text, so pin them to one upstream commit."""

    commit = "5beb35b040e3de97e54fa9e386d7e42d15c295c2"
    # sha256 of the unmodified upstream files at `commit`.
    files = {
        "LICENSE": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5",
        "code-review/SKILL.md": "09eb147f793e4647949edd32dbad278f0554dfb56e0d46b699cd4c2c55bf0357",
        "retro/SKILL.md": "33fbc28568e3146f20fd908b12998bc0ab30aa4f4c87288199a40793efa94696",
        "writing-for-agents/SKILL.md": "551adca942227b44192edba88acd4e8db911f0121ce58ad16944ccf6a896a74a",
        "writing-for-agents/SKILL-MECHANICS.md":
            "c768e6307c7c10728c401c213f2c4ba71c542127eeb7ad2956aabd15a0fa0059",
    }
    skills = CONTROL.parent / "skills"

    def test_vendored_files_match_pinned_commit(self):
        present = {path.relative_to(self.skills).as_posix() for path in self.skills.rglob("*")
                   if path.is_file()}
        self.assertEqual(present, {*self.files, "README.md"})
        for name, digest in self.files.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((self.skills / name).read_bytes()).hexdigest(), digest)
        readme = (self.skills / "README.md").read_text()
        self.assertIn(self.commit, readme)
        for name in self.files:
            if name != "LICENSE":
                self.assertIn(Path(name).name, readme)

    def test_dependencies_are_vendored(self):
        for name in self.files:
            if not name.endswith(".md"):
                continue
            text = (self.skills / name).read_text()
            with self.subTest(name=name):
                for target in re.findall(r"\]\(([^)#]+)\)", text):
                    if not re.match(r"[a-z]+:", target):
                        self.assertTrue((self.skills / name).parent.joinpath(target).is_file(), target)
                for skill in re.findall(r"Skill tool with `([a-z-]+)`", text):
                    self.assertTrue((self.skills / skill / "SKILL.md").is_file(), skill)

    def test_review_axes_parse_from_pinned_skill(self):
        axes = control.review_axes()
        self.assertEqual(set(axes), {"standards", "spec"})
        self.assertTrue(axes["standards"]["brief"].startswith("Report, per file/hunk"))
        self.assertTrue(axes["spec"]["brief"].startswith("Report: (a) requirements"))
        self.assertTrue(axes["standards"]["context"].startswith("### 3. Identify the standards sources"))


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

    def test_unlimited_scan_accepts_any_size_but_still_finds_credentials(self):
        large = "检查🙂 é\n" * (control.MAX_ARTIFACT_BYTES // 4)
        self.assertGreater(len(large.encode()), control.MAX_ARTIFACT_BYTES)
        control.scan(self.artifact(large), limit=None)
        control.scan(self.artifact(large), public=True, limit=None)
        # A leak at the very end of a large artifact is still found.
        for leak, reason in ((SECRET, "credential-pattern-in-artifact"),
                             ('Zq9/"opaque+cred', "credential-in-artifact")):
            for public in (False, True):
                with self.subTest(reason=reason, public=public), \
                        self.assertRaisesRegex(ValueError, f"^{reason}$"):
                    control.scan(self.artifact(large + leak), public=public, limit=None)
        with mock.patch.dict(os.environ):
            del os.environ["FACTORY_AUTH_FILE"]
            with self.assertRaisesRegex(ValueError, "^missing-auth-file$"):
                control.scan(self.artifact(large), limit=None)

    def test_cli_scan_output_is_private_and_unlimited(self):
        def run(content, env):
            return subprocess.run([sys.executable, "-I", str(CONTROL), "scan-output", self.artifact(content)],
                                  capture_output=True, text=True, env=env)
        large = "ü" * control.MAX_ARTIFACT_BYTES
        result = run(large, {**os.environ})
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        result = run(large + SECRET, {**os.environ})
        self.assertEqual((result.returncode, result.stderr), (1, "::error::credential-pattern-in-artifact\n"))
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        result = run("ok", {key: value for key, value in os.environ.items() if key != "FACTORY_AUTH_FILE"})
        self.assertEqual((result.returncode, result.stderr), (1, "::error::missing-auth-file\n"))

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

    def events(self, *texts, extra=(), name="events.jsonl"):
        path = self.directory / name
        lines = [json.dumps({"type": "step_start"})]
        lines += [json.dumps({"type": "text", "part": {"text": text}}) for text in texts]
        lines += [json.dumps(event) for event in extra]
        path.write_text("\n".join(lines) + "\n")
        return str(path)

    def axis(self, *findings, name):
        return self.events(json.dumps({"findings": [{"blocking": blocking, "finding": finding}
                                                    for blocking, finding in findings]}), name=name)

    def review(self, standards=(), spec=()):
        return control.review(self.axis(*standards, name="standards.jsonl"),
                              self.axis(*spec, name="spec.jsonl"))

    def assertRejects(self, reason, filename):
        clean = self.axis(name="clean.jsonl")
        for args in ((filename, clean), (clean, filename)):
            with self.subTest(axis="standards" if args[0] == filename else "spec"), \
                    self.assertRaises(ValueError) as caught:
                control.review(*args)
            self.assertEqual(str(caught.exception), reason)

    def test_accepts_approval(self):
        empty = self.events('{"findings":', '[]}', name="split.jsonl")
        self.assertEqual(control.review(empty, empty),
                         {"verdict": "approve", "findings": [], "advisory": []})

    def test_advisory_findings_do_not_block(self):
        self.assertEqual(self.review(standards=[(False, "src/a.ts: possible Feature Envy")]), {
            "verdict": "approve", "findings": [],
            "advisory": ["Standards: src/a.ts: possible Feature Envy"]})

    def test_blocking_finding_on_either_axis_requests_changes(self):
        for standards, spec in (([(True, "x")], []), ([], [(True, "x")])):
            with self.subTest(standards=standards, spec=spec):
                self.assertEqual(self.review(standards, spec)["verdict"], "request_changes")

    def test_findings_keep_axis_labels_and_order(self):
        result = self.review(standards=[(True, "a"), (False, "b")], spec=[(False, "c"), (True, "d")])
        self.assertEqual(result, {"verdict": "request_changes", "findings": ["Standards: a", "Spec: d"],
                                  "advisory": ["Standards: b", "Spec: c"]})

    def test_rejects_error_events(self):
        for event in ({"type": "error"}, {"type": "step_finish", "error": {"message": "boom"}}):
            with self.subTest(event=event):
                self.assertRejects("invalid-events", self.events('{"findings":[]}', extra=[event]))

    def test_rejects_provider_truncated_replies(self):
        # A truncated reply can still parse, so the finish reason decides completeness.
        for reason in ("length", "content-filter"):
            with self.subTest(reason=reason):
                self.assertRejects("incomplete-output", self.events(
                    '{"findings":[]}', extra=[{"type": "step_finish", "part": {"reason": reason}}]))

    def test_rejects_non_object_events(self):
        path = self.directory / "list.jsonl"
        path.write_text('["type", "text"]\n')
        self.assertRejects("invalid-events", str(path))
        path.write_text("")
        self.assertRejects("invalid-events", str(path))

    def test_rejects_malformed_schema(self):
        item = {"blocking": True, "finding": "x"}
        for text, reason in (
            ("Looks good!", "invalid-review"),
            ('```json\n{"findings":[]}\n```', "invalid-review"),
            ('["findings"]', "invalid-review"),
            ("{}", "invalid-review"),
            ('{"verdict":"approve","findings":[]}', "invalid-review"),
            ('{"findings":[],"extra":1}', "invalid-review"),
            ('{"findings":[{"blocking":true,"finding":"x"}],"findings":[]}', "invalid-review"),
            ('{"findings":[{"blocking":true,"blocking":false,"finding":"x"}]}', "invalid-review"),
            ('{"findings":"x"}', "invalid-findings"),
            ('{"findings":["x"]}', "invalid-findings"),
            ('{"findings":[{"finding":"x"}]}', "invalid-findings"),
            ('{"findings":[{"blocking":true,"finding":"x","axis":"spec"}]}', "invalid-findings"),
            ('{"findings":[{"blocking":"true","finding":"x"}]}', "invalid-findings"),
            ('{"findings":[{"blocking":1,"finding":"x"}]}', "invalid-findings"),
            ('{"findings":[{"blocking":true,"finding":"  "}]}', "invalid-findings"),
            ('{"findings":[{"blocking":true,"finding":1}]}', "invalid-findings"),
        ):
            with self.subTest(text=text[:60]):
                self.assertRejects(reason, self.events(text))

    def test_findings_have_no_count_or_length_limit(self):
        finding = "src/a.ts: 名前が不明瞭 🙂 " + "x" * 50_000
        result = self.review([(True, finding)] * 100, [(False, finding)] * 100)
        self.assertEqual(set(result), {"verdict", "findings", "advisory"})
        self.assertEqual(result["findings"], [f"Standards: {finding}"] * 100)
        self.assertEqual(result["advisory"], [f"Spec: {finding}"] * 100)

    def test_cli_writes_review_output(self):
        output = self.directory / "review.json"
        result = subprocess.run(
            [sys.executable, "-I", str(CONTROL), "review", self.axis((False, "b"), name="standards.jsonl"),
             self.axis((True, "d"), name="spec.jsonl")],
            capture_output=True, text=True, env={**os.environ, "REVIEW_OUTPUT": str(output)})
        self.assertEqual((result.returncode, result.stdout), (0, "request_changes\n"), result.stderr)
        self.assertEqual(json.loads(output.read_text()),
                         {"verdict": "request_changes", "findings": ["Spec: d"], "advisory": ["Standards: b"]})
        result = subprocess.run([sys.executable, "-I", str(CONTROL), "review", str(output)],
                                capture_output=True, text=True, env={**os.environ, "REVIEW_OUTPUT": str(output)})
        self.assertEqual(result.returncode, 1)


class EventsTest(unittest.TestCase):
    def test_rejects_unparseable_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text('{"type":"text"}\nnot json\n')
            with self.assertRaisesRegex(ValueError, "^invalid-events$"):
                control.events(str(path))
            path.write_text('{"type":"step_start"}\n{"type":"text","part":{"text":"done"}}\n')
            self.assertEqual(len(control.events(str(path))), 2)


class TranscriptTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.events = self.directory / "events.jsonl"
        self.output = self.directory / "session.md"

    def transcript(self, *lines):
        self.events.write_text("".join(line if isinstance(line, str) else json.dumps(line) + "\n"
                                       for line in lines))
        control.transcript(str(self.events), str(self.output))
        return self.output.read_text()

    def test_renders_readable_events_in_order(self):
        text = self.transcript(
            {"type": "step_start", "timestamp": 1_000_000},
            {"type": "reasoning", "timestamp": 1_002_500, "part": {"text": "Plan the test."}},
            {"type": "tool_use", "timestamp": 1_005_000, "part": {"tool": "read", "state": {
                "status": "completed", "input": {"filePath": "src/a.ts"}, "output": "one"}}},
            {"type": "tool_use", "part": {"tool": "bash", "state": {"status": "error", "error": "exit 1"}}},
            {"type": "step_finish", "part": {"reason": "stop", "tokens": {"input": 3}}},
            "not json\n")
        raw = self.events.read_text().splitlines()
        expected = [
            '### 1 step_start +0s\n{"type": "step_start", "timestamp": 1000000}',
            "### 2 reasoning +2s\nPlan the test.",
            '### 3 tool_use +5s\nread completed\ninput: {"filePath": "src/a.ts"}\noutput: one',
            "### 4 tool_use\nbash error\ninput: null\noutput: exit 1",
            '### 5 step_finish\nreason: stop, tokens: {"input": 3}',
        ]
        self.assertEqual(text, "\n\n".join(f"{body}\n\nRaw event:\n{line}"
                                            for body, line in zip(expected, raw))
                         + "\n\n### 6 unparseable\nnot json\n")

    def test_keeps_long_fields_whole(self):
        self.assertFalse(hasattr(control, "MAX_TRANSCRIPT_FIELD"))
        long = "长🙂 " * 20_000
        text = self.transcript({"type": "text", "part": {"text": long}},
                               {"type": "tool_use", "part": {"tool": "read", "state": {
                                   "status": "completed", "input": {"filePath": "é" * 5_000}, "output": long}}})
        raw = self.events.read_text().splitlines()
        self.assertEqual(text, f"### 1 text\n{long}\n\nRaw event:\n{raw[0]}\n\n"
                         f'### 2 tool_use\nread completed\ninput: {json.dumps({"filePath": "é" * 5_000}, ensure_ascii=False)}\n'
                         f"output: {long}\n\nRaw event:\n{raw[1]}\n")
        self.assertNotIn("more characters", text)

    def test_tolerates_missing_and_hostile_events(self):
        control.transcript(str(self.directory / "missing.jsonl"), str(self.output))
        self.assertEqual(self.output.read_text(), "No events were recorded.\n")
        text = self.transcript([1], {"type": "tool_use", "part": {"tool": {"x": 1}, "state": []}},
                               {"type": "text", "part": "x"}, "[" * 100_000 + "\n", b"\xff".decode("latin-1"))
        self.assertIn("### 1 unparseable", text)
        self.assertIn("### 4 unparseable", text)

    def test_keeps_every_event_of_a_large_session(self):
        self.assertFalse(hasattr(control, "MAX_TRANSCRIPT_BYTES"))
        text = self.transcript(*({"type": "text", "part": {"text": f"event {n} " + "ü" * 1000}}
                                 for n in range(4000)))
        self.assertGreater(len(text.encode()), 8_000_000)
        raw = self.events.read_text().splitlines()
        self.assertEqual(text, "\n\n".join(f"### {n + 1} text\nevent {n} " + "ü" * 1000
                                           + f"\n\nRaw event:\n{raw[n]}" for n in range(4000)) + "\n")

    def test_retains_unknown_metadata_and_exact_raw_lines(self):
        raw = '  {"type":"text", "extra":{"a":[1]}, "part":{"text":"ok", "metadata":"kept"}}  \n'
        self.assertIn(raw, self.transcript(raw))
        auth = self.directory / "auth.json"
        auth.write_text(json.dumps({"key": "opaque-credential-value"}))
        self.transcript({"type": "tool_use", "part": {"tool": "read", "state": {
            "output": "clean", "metadata": "opaque-credential-value"}}})
        with mock.patch.dict(os.environ, {"FACTORY_AUTH_FILE": str(auth)}), \
                self.assertRaisesRegex(ValueError, "^credential-in-artifact$"):
            control.scan(str(self.output), limit=None)

    def test_session_scan_allows_any_transcript_size_but_rejects_credentials(self):
        auth = self.directory / "auth.json"
        auth.write_text(json.dumps({"key": "opaque-credential-value"}))
        large = [{"type": "text", "part": {"text": "x" * 1000}}] * 600
        with mock.patch.dict(os.environ, {"FACTORY_AUTH_FILE": str(auth)}):
            self.transcript(*large)
            with self.assertRaisesRegex(ValueError, "^artifact-too-large$"):
                control.scan(str(self.output))
            control.scan(str(self.output), limit=None)
            for leak, reason in (("opaque-credential-value", "credential-in-artifact"),
                                 (SECRET, "credential-pattern-in-artifact")):
                with self.subTest(leak=leak[:6]), self.assertRaisesRegex(ValueError, f"^{reason}$"):
                    self.transcript(*large, {"type": "tool_use", "part": {"tool": "read", "state": {"output": leak}}})
                    control.scan(str(self.output), limit=None)
            result = subprocess.run([sys.executable, "-I", str(CONTROL), "scan-session", str(self.output)],
                                    capture_output=True, text=True, env={**os.environ})
            self.assertEqual((result.returncode, result.stderr), (1, "::error::credential-pattern-in-artifact\n"))
            self.transcript(*large)
            result = subprocess.run([sys.executable, "-I", str(CONTROL), "scan-session", str(self.output)],
                                    capture_output=True, text=True, env={**os.environ})
            self.assertEqual(result.returncode, 0, result.stderr)


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

    jobs = {"implement": ("software-factory-round.yml", "implement"),
            "review": ("software-factory-round.yml", "review"),
            "retro": ("software-factory-implement.yml", "retro"),
            "publish": ("software-factory-implement.yml", "retro-publish")}

    def run_step(self, job, opencode="exit 0", gh="exit 0", select="opencode run", env=None, files=None):
        workflow, name = self.jobs[job]
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.directory = directory
        (directory / "trusted").symlink_to(CONTROL.parents[2])
        # Publishing steps run from a plain checkout of the trusted revision.
        (directory / ".github").symlink_to(CONTROL.parents[2] / ".github")
        (directory / "candidate").mkdir()
        (directory / "workspace").mkdir()
        bin_dir = directory / "bin"
        bin_dir.mkdir()
        # A real deadline shortened to one second; exit 124 mirrors coreutils timeout.
        (bin_dir / "timeout").write_text(
            f"#!{sys.executable}\nimport subprocess, sys\nargs = sys.argv[1:]\n"
            "while args[0].startswith('-'): args.pop(0)\n"
            "try: sys.exit(subprocess.run(args[1:], timeout=1).returncode)\n"
            "except subprocess.TimeoutExpired: sys.exit(124)\n")
        # Every call is logged in order, NUL-separated, so tests can count sessions and calls.
        log = 'printf "%s\\0" "$@" > "$CALLS/$(printf %03d $(($(ls "$CALLS" | wc -l))))"\n'
        (bin_dir / "opencode").write_text(f"#!/bin/bash\n{log}{opencode}\n")
        (bin_dir / "gh").write_text(f"#!/bin/bash\n{log}{gh}\n")
        for stub in bin_dir.iterdir():
            stub.chmod(0o755)
        (directory / "calls").mkdir()
        auth = directory / "auth.json"
        auth.write_text(json.dumps({"key": SECRET}))
        (directory / "temp").mkdir()
        for filename, content in (files or {}).items():
            (directory / filename).parent.mkdir(parents=True, exist_ok=True)
            (directory / filename).write_text(content)
        steps = WorkflowContractTest.load(workflow)["jobs"][name]["steps"]
        step = next(step for step in steps if select in step.get("run", "") or select == step.get("name"))
        cwd = directory / step["working-directory"] if "working-directory" in step else directory
        env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "MODEL": control.MODEL, "ISSUE": "6",
               "ROUND": "1", "RUNNER_TEMP": str(directory / "temp"), "FACTORY_AUTH_FILE": str(auth),
               "GITHUB_OUTPUT": str(directory / "output"), "GITHUB_STEP_SUMMARY": str(directory / "summary"),
               "GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": "123", "CALLS": str(directory / "calls"),
               "REVIEW_OUTPUT": str(directory / "temp/feedback/review.json"), **(env or {})}
        result = subprocess.run(["bash", "-e", "-c", step["run"]], cwd=cwd, env=env,
                                capture_output=True, text=True, timeout=30)
        return result, (directory / "summary").read_text() if (directory / "summary").exists() else ""

    def calls(self, program):
        calls = [path.read_text().split("\0")[:-1] for path in sorted((self.directory / "calls").iterdir())]
        return [call for call in calls if (call[:1] == ["run"]) == (program == "opencode")]

    def stub_events(self, *events):
        return "\n".join(f"echo '{json.dumps(event)}'" for event in events)

    def reply(self, value):
        return self.stub_events({"type": "text", "part": {"text": json.dumps(value)}})

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
                # A timed-out review stops before the second axis spends its budget.
                self.assertEqual(len(self.calls("opencode")), 1)

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

    def test_review_runs_each_axis_in_its_own_session(self):
        result, summary = self.run_step("review", self.reply(
            {"findings": [{"blocking": False, "finding": "src/a.ts: possible Mysterious Name"}]}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(summary.count("### OpenCode run"), 2)
        sessions = self.calls("opencode")
        self.assertEqual(len(sessions), 2)
        axes = control.review_axes()
        for (axis, prompt), session in zip((("standards", "spec"), ("spec", "standards")), sessions):
            with self.subTest(axis=axis):
                self.assertIn("--standalone", session)
                self.assertIn(axes[axis]["brief"], session[-1])
                self.assertNotIn(axes[prompt]["brief"], session[-1])
                self.assertTrue((self.directory / f"temp/review-{axis}.jsonl").is_file())
        self.assertEqual((self.directory / "output").read_text(), "verdict=approve\n")
        self.assertEqual(json.loads((self.directory / "temp/feedback/review.json").read_text())["advisory"],
                         ["Standards: src/a.ts: possible Mysterious Name", "Spec: src/a.ts: possible Mysterious Name"])


    def test_review_rejects_old_schema(self):
        result, _ = self.run_step("review", self.reply({"verdict": "approve", "findings": []}))
        self.assertEqual(result.returncode, 1)
        self.assertIn("::error::invalid-review", result.stderr)
        self.assertFalse((self.directory / "output").exists())


    def test_sessions_are_always_recorded_and_scanned(self):
        for job, events in (("implement", ["implementation"]), ("review", ["review-standards", "review-spec"])):
            with self.subTest(job=job):
                # A run that died before writing any event still yields a transcript.
                result, _ = self.run_step(job, select="control.py transcript")
                self.assertEqual(result.returncode, 0, result.stderr)
                sessions = sorted((self.directory / "temp/session").iterdir())
                self.assertEqual(len(sessions), len(events))
                for session in sessions:
                    self.assertEqual(session.read_text(), "No events were recorded.\n")
                summaries = {f"temp/{name}-summary.txt": 'opencode-summary {"exit_status": 124}\n'
                             for name in events}
                # The implementation's shell can leave other files beside the transcripts.
                summaries["temp/session/leak.txt"] = SECRET
                result, _ = self.run_step(job, select="control.py transcript", files=summaries)
                self.assertEqual(result.returncode, 0, result.stderr)
                saved = list((self.directory / "temp/session").glob("*-summary.txt"))
                self.assertEqual(len(saved), len(events))
                self.assertTrue(all('"exit_status": 124' in path.read_text() for path in saved))
                uploaded = self.uploaded(job)
                self.assertEqual(len(uploaded), 2 * len(events))
                self.assertNotIn("leak.txt", uploaded)
                leak = json.dumps({"type": "text", "part": {"text": SECRET}}) + "\n"
                result, _ = self.run_step(job, select="control.py transcript",
                                          files={f"temp/{name}.jsonl": leak for name in events})
                self.assertEqual(result.returncode, 1)
                self.assertIn("::error::credential-in-artifact", result.stderr)
                self.assertNotIn(SECRET, result.stdout + result.stderr)

    def uploaded(self, job):
        """Files the session upload step would pick up from the last run's temp directory."""
        workflow, name = self.jobs[job]
        upload = next(step for step in WorkflowContractTest.load(workflow)["jobs"][name]["steps"]
                      if str(step.get("with", {}).get("name", "")).startswith("session-"))
        paths = (Path(line.replace("${{ runner.temp }}", str(self.directory / "temp"))
                      .replace("${{ inputs.round }}", "1")) for line in upload["with"]["path"].splitlines())
        return [file.name for path in paths
                for file in (sorted(path.rglob("*")) if path.is_dir() else [path]) if file.is_file()]


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
        shared = [*(CONTROL.parent / "prompts").glob("*.md"),
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
        handoff = self.implement["jobs"]["handoff"]
        self.assertEqual(downloads(handoff), {"checked-${{ steps.approved.outputs.round }}", "factory-claim"})
        self.assertNotIn("advisory", str(handoff))
        self.assertNotIn("review.json", str(handoff))


    def jobs(self):
        for workflow in (self.implement, self.round):
            yield from workflow["jobs"].items()

    def opencode_steps(self):
        return {name: step for name, job in self.jobs() for step in job.get("steps", [])
                if "opencode run" in step.get("run", "")}

    def test_model_deadlines(self):
        steps = self.opencode_steps()
        self.assertEqual(set(steps), {"implement", "review"})
        for name, seconds in (("implement", 1500), ("review", 600)):
            with self.subTest(job=name):
                self.assertEqual(re.findall(r"timeout --kill-after=15 (\d+) opencode run", steps[name]["run"]),
                                 [str(seconds)])

    def test_review_runs_both_axes_and_aggregates_both_files(self):
        run = self.opencode_steps()["review"]["run"]
        self.assertIn("for axis in standards spec; do", run)
        self.assertIn('prompt "review-$axis"', run)
        self.assertIn('> "$RUNNER_TEMP/review-$axis.jsonl"', run)
        self.assertRegex(run, r'control\.py review \\\s+"\$RUNNER_TEMP/review-standards\.jsonl" '
                              r'"\$RUNNER_TEMP/review-spec\.jsonl"\)')

    def test_only_implementation_gets_shell(self):
        modes = {name: re.findall(r"control\.py configure \S+ (\w+)", step["run"])
                 for name, job in self.jobs() for step in job.get("steps", [])
                 if "control.py configure" in step.get("run", "")}
        self.assertEqual(modes, {"implement": ["implement"], "review": ["review"]})

    def test_sessions_are_always_scanned_then_uploaded_for_three_days(self):
        uploads = 0
        for name, job in self.jobs():
            steps = job.get("steps", [])
            for index, step in enumerate(steps):
                if not str(step.get("with", {}).get("name", "")).startswith("session-"):
                    continue
                uploads += 1
                with self.subTest(job=name):
                    record = steps[index - 1]
                    self.assertEqual((record.get("id"), record.get("if")), ("session", "always()"))
                    self.assertTrue(record.get("continue-on-error"))
                    run = record["run"]
                    self.assertLess(run.index("control.py transcript"), run.index("control.py scan-session"))
                    self.assertEqual(run.count("control.py transcript"), 1)
                    self.assertEqual(run.count("control.py scan-session"), 2)
                    self.assertLess(run.index('scan-session "$RUNNER_TEMP/'), run.index('cp "$RUNNER_TEMP/'))
                    self.assertEqual(step["if"], "always() && steps.session.outcome == 'success'")
                    # Exact scanned files only, never the whole directory or a wildcard.
                    paths = step["with"]["path"].splitlines()
                    for path in paths:
                        self.assertTrue(path.startswith("${{ runner.temp }}/session/"), path)
                        self.assertTrue(path.endswith((".md", "-summary.txt")), path)
                        self.assertNotIn("*", path)
                    self.assertEqual(step["with"]["retention-days"], 3)
        self.assertEqual(uploads, 2)

    def test_every_factory_artifact_expires_after_three_days(self):
        for name, job in self.jobs():
            for step in job.get("steps", []):
                if "upload-artifact" in step.get("uses", ""):
                    with self.subTest(job=name, artifact=step["with"]["name"]):
                        self.assertEqual(step["with"]["retention-days"], 3)


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

    def test_review_and_retro_are_read_only(self):
        for mode in ("review",):
            with self.subTest(mode=mode):
                config = self.configure(mode)
                self.assertFalse(config["share"])
                self.assertEqual(config["permission"]["read"], {
                    "*": "allow", ".env": "deny", ".env.*": "deny", "**/.env": "deny",
                    "**/.env.*": "deny", "**/auth.json": "deny"})
                self.assertEqual(config["permission"]["*"], "deny")
                self.assertEqual(config["permission"]["edit"], "deny")
                for tool in self.denied:
                    self.assertEqual(config["permission"][tool], "deny")
                allowed = {tool for tool, rule in config["permission"].items() if rule == "allow"}
                self.assertEqual(allowed, {"glob", "grep", "list"})

    def test_implement_edits_only_allowed_paths(self):
        names = ["src/a.ts", "packages/core/test/b.test.ts"]
        (self.root / "tasks" / "1.json").write_text(json.dumps({**self.spec, "allowed_paths": names}))
        permission = self.configure("implement")["permission"]
        self.assertEqual(permission["edit"], {"*": "deny", **{name: "allow" for name in names}})
        # Last match wins in OpenCode, so the catch-all deny must precede the allows.
        self.assertEqual(list(permission["edit"]), ["*", *names])
        self.assertFalse(any(key.startswith("/") for key in permission["edit"]))
        # Shell lets implementation run typecheck and tests; verify rechecks on a fresh runner.
        self.assertEqual(permission["bash"], "allow")
        for tool in self.denied:
            if tool != "bash":
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
