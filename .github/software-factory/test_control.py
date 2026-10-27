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
import artifacts  # noqa: E402
import authorization  # noqa: E402
import control  # noqa: E402

CONTROL = Path(control.__file__).resolve()
OWNER = "owner"
REPO = f"{OWNER}/tanomu"
BODY = "Merge private messages.\nBlocked by: #2\n"
SECRET = "sk-test-0123456789abcdefghijklmnop"


class TaskDirectory(unittest.TestCase):
    """A temporary trusted controller root; no per-issue configuration."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.object(control, "ROOT", self.root))

    def assertRejects(self, reason, function, *args):
        with self.assertRaises(ValueError) as caught:
            function(*args)
        self.assertEqual(str(caught.exception), reason)


class TaskTest(TaskDirectory):
    def test_deterministic_safe_metadata_without_task_files(self):
        self.assertEqual(control.metadata("10"), {
            "issue": "10", "branch": "feat/10-implement", "title": "feat(repo): implement issue #10"})
        for number in ("0", "01", "1/../1", "-1", "1 ", ""):
            self.assertRejects("invalid-issue", control.metadata, number)

    def real_prompts(self):
        for name in ("prompts", "skills"):
            shutil.copytree(CONTROL.parent / name, self.root / name)

    def test_implement_prompt_uses_issue_only(self):
        self.real_prompts()
        text = control.prompt("implement", "1")
        self.assertTrue(text.startswith((CONTROL.parent / "prompts/implement.md").read_text()))
        self.assertIn("frozen gate snapshot", text)
        self.assertNotIn("task.json", text)

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
        self.assertIn("sole spec is the gate snapshot .factory-input/issue.md", spec)
        self.assertNotIn("Check the thing.", standards)

    def test_rejects_unknown_prompt_modes(self):
        self.real_prompts()
        for mode in ("acceptance", "review", "review-", "review-security", "retro"):
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


class SkillPinTest(unittest.TestCase):
    """The vendored skills are trusted prompt text, so pin them to one upstream commit."""

    commit = "5beb35b040e3de97e54fa9e386d7e42d15c295c2"
    # sha256 of the unmodified upstream files at `commit`.
    files = {
        "LICENSE": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5",
        "code-review/SKILL.md": "09eb147f793e4647949edd32dbad278f0554dfb56e0d46b699cd4c2c55bf0357",
        "pr/SKILL.md": "ab63f1cf78647389edcd386c9427c5dfca27ed2836930c24773ffee834c19bcd",
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
        self.assertEqual(set(axes), {"standards", "spec", "security"})
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
        artifacts.scope("1", self.base)

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

    def test_accepts_unrestricted_feature_paths_additions_and_deletions(self):
        for name in (".github/workflows/ci.yml", ".github/software-factory/control.py", "package.json",
                     ".env.example", "apps/server/drizzle/001.sql", "deploy/run.sh", "dir with space/x"):
            self.write(name, "feature source\n")
        (self.repo / "README.md").unlink()
        self.scope()

    def test_rejects_untracked_symlink(self):
        os.symlink("/etc/passwd", self.repo / "src/new.ts")
        self.assertRejects("invalid-file-type", self.scope)

    def test_rejects_replacing_file_with_symlink(self):
        (self.repo / "src/a.ts").unlink()
        os.symlink("../README.md", self.repo / "src/a.ts")
        self.assertRejects("invalid-file-type", self.scope)

    def test_accepts_executable_mode(self):
        os.chmod(self.repo / "src/a.ts", 0o755)
        self.scope()

    def test_accepts_new_executable_file(self):
        os.chmod(self.write("src/new.ts", "x\n"), 0o755)
        self.scope()

    def test_rejects_binary_file(self):
        self.write("src/new.ts", b"\x00\x01\x02binary")
        self.assertRejects("binary-patch", self.scope)

    def test_rejects_patch_over_line_limit(self):
        self.write("src/new.ts", "x\n" * 601)
        self.assertRejects("patch-too-large", self.scope)

    def test_accepts_patch_at_line_limit(self):
        # 2 removed + 598 added == 600.
        self.write("src/a.ts", "x\n" * 598)
        self.scope()

    def test_line_limit_counts_untracked_files(self):
        self.write("src/a.ts", "one\nthree\n")
        self.write("src/new.ts", "x\n" * 599)
        self.assertRejects("patch-too-large", self.scope)

    def test_generated_files_do_not_count_towards_limit(self):
        self.write("pnpm-lock.yaml", "generated\n" * 900)
        self.write("apps/server/drizzle/meta/0001_snapshot.json", "generated\n" * 900)
        self.write("src/new.ts", "feature\n" * 600)
        self.scope()

    def test_rejects_whitespace_errors(self):
        self.write("src/a.ts", "one\ntwo  \n")
        self.assertRejects("whitespace-error", self.scope)

    def test_rejects_invalid_base(self):
        self.write("src/a.ts", "one\nthree\n")
        for base in ("--output=/tmp/x", "does-not-exist", "0" * 40):
            with self.subTest(base=base):
                self.assertRejects("invalid-base", artifacts.scope, "1", base)

    def test_accepts_symbolic_base(self):
        self.write("src/a.ts", "one\nthree\n")
        artifacts.scope("1", "main")


def issue(**overrides):
    value = {"state": "open", "user": {"login": OWNER}, "body": BODY,
             "labels": [{"name": "ready-for-agent"}, {"name": "agent:implement"}]}
    value.update(overrides)
    return value


def labeled(event, actor, name="agent:implement"):
    return {"id": 456, "event": event, "actor": {"login": actor}, "label": {"name": name}}


class GateTest(TaskDirectory):
    def setUp(self):
        super().setUp()
        self.out = Path(self.enterContext(tempfile.TemporaryDirectory())) / "input"
        self.enterContext(mock.patch.dict(os.environ, {
            "GITHUB_REF": "refs/heads/main", "GITHUB_REPOSITORY": REPO,
            "GITHUB_ACTOR": OWNER, "GITHUB_TRIGGERING_ACTOR": OWNER,
            "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
        }))
        self.issue = issue()
        self.dependency = {"state": "closed", "state_reason": "completed"}
        self.refs = []
        self.pulls = []
        self.pages = [[labeled("labeled", "intruder"), labeled("unlabeled", OWNER)],
                      [labeled("labeled", "intruder", "ready-for-agent"),
                       labeled("labeled", OWNER), {"event": "commented"}]]
        self.calls = []
        self.enterContext(mock.patch.object(authorization, "api", self.fake_api))
        self.enterContext(mock.patch.object(authorization.subprocess, "check_output", self.fake_events))

    def fake_api(self, path):
        self.calls.append(path)
        return {
            f"repos/{REPO}/issues/1": self.issue,
            f"repos/{REPO}/issues/2": self.dependency,
            f"repos/{REPO}/git/matching-refs/heads/feat/1-implement": self.refs,
            f"repos/{REPO}/pulls?state=all&head={OWNER}:feat/1-implement": self.pulls,
        }[path]

    def fake_events(self, command):
        self.assertEqual(command, ["gh", "api", "--paginate", "--slurp",
                                   f"repos/{REPO}/issues/1/events?per_page=100"])
        return json.dumps(self.pages).encode()

    def gate(self):
        authorization.gate("1", str(self.out))

    def test_accepts_authorized_issue_and_writes_body(self):
        self.gate()
        self.assertEqual((self.out / "issue.md").read_text(), BODY)
        self.assertIn(f"repos/{REPO}/issues/2", self.calls)

    def test_rejects_environment(self):
        for key, value, reason in (
            ("GITHUB_REF", "refs/heads/feature", "wrong-ref"),
            ("GITHUB_REF", "refs/pull/1/merge", "wrong-ref"),
            ("GITHUB_ACTOR", "intruder", "wrong-actor"),
            ("GITHUB_TRIGGERING_ACTOR", "intruder", "wrong-triggering-actor"),
        ):
            with self.subTest(key=key, value=value), mock.patch.dict(os.environ, {key: value}):
                self.assertRejects(reason, self.gate)
        self.assertEqual(self.calls, [])


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


    def test_rejects_label_from_non_owner(self):
        self.pages = [[labeled("labeled", OWNER)], [labeled("labeled", "intruder")]]
        self.assertRejects("wrong-label-actor", self.gate)

    def test_rejects_label_without_event_history(self):
        self.pages = [[labeled("labeled", OWNER, "ready-for-agent")]]
        self.assertRejects("wrong-label-actor", self.gate)

    def test_rejects_owner_label_later_removed(self):
        self.pages = [[labeled("labeled", OWNER), labeled("unlabeled", OWNER)]]
        self.assertRejects("wrong-label-actor", self.gate)

    def test_gate_captures_any_current_body_without_manual_config(self):
        self.issue["body"] = "Implement issue ten. Refs #99. bLoCkEd By #2"
        self.gate()
        captured = authorization.snapshot("1", str(self.out))
        self.assertEqual(captured["blocked_by"], ["2"])
        self.assertEqual((self.out / "issue.md").read_text(), self.issue["body"])
        self.issue["body"] += " changed"
        self.assertRejects("body-changed", control.revalidate, "1", str(self.out))

    def test_crlf_snapshot_survives_gate_and_claim(self):
        self.issue["body"] = "Feature.\r\nBlocked by: #2\r\n"
        self.issue["labels"] = [{"name": n} for n in ("ready-for-agent", "agent:implement")]
        self.pages = [[labeled("labeled", OWNER)]]
        authorization.gate("1", str(self.out))
        authorization.revalidate("1", str(self.out))
        self.issue["labels"] = [{"name": n} for n in ("ready-for-agent", "implementing")]
        self.pages = [[{**labeled("labeled", "github-actions[bot]", "implementing"), "id": 987}]]
        authorization.record_claim("1", str(self.out), str(self.root / "claim.json"))
        self.assertEqual((self.out / "issue.md").read_bytes(), self.issue["body"].encode())

    def test_issue_ten_needs_no_task_file(self):
        with mock.patch.object(authorization, "api", side_effect=lambda path: self.issue if path.endswith("issues/10") else []), \
                mock.patch.object(authorization.subprocess, "check_output", return_value=json.dumps(self.pages).encode()):
            self.issue["body"] = "Feature without task JSON. Refs #99."
            authorization.gate("10", str(self.out))
        self.assertEqual(authorization.snapshot("10", str(self.out))["branch"], "feat/10-implement")

    def test_rejects_unfinished_dependency(self):
        for dependency in ({"state": "open", "state_reason": None},
                           {"state": "closed", "state_reason": "not_planned"},
                           {"state": "closed", "state_reason": "duplicate"},
                           {"state": "closed"}):
            with self.subTest(dependency=dependency):
                self.dependency = dependency
                self.assertRejects("open-dependency", self.gate)

    def test_native_dependency_summary_blocks_gate(self):
        self.issue["issue_dependencies_summary"] = {"blocked_by": 1}
        self.assertRejects("open-dependency", self.gate)

    def test_only_explicit_same_repo_refs_are_dependencies(self):
        self.assertEqual(authorization.dependencies(
            "Refs #3. blocked BY: #2, #7; Blocked by #4. Blocked by owner/repo#5. "
            "Blocked by https://github.com/x/y/issues/6. bLoCkEd By #2"), ["2", "7", "4"])

    def test_rejects_existing_branch(self):
        self.refs = [{"ref": "refs/heads/feat/1-implement"}]
        self.assertRejects("branch-exists", self.gate)

    def test_ignores_branch_prefix_matches(self):
        self.refs = [{"ref": "refs/heads/feat/1-implement-old"}]
        self.gate()

    def test_rejects_existing_pull_request(self):
        self.pulls = [{"number": 9}]
        self.assertRejects("pr-exists", self.gate)


class FeedbackTest(GateTest):
    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.object(control, "api", self.fake_api))
        self.enterContext(mock.patch.dict(os.environ, {
            "EVENT_NAME": "issues", "LABEL_NAME": "agent:implement",
            "GITHUB_STEP_SUMMARY": str(self.root / "summary"),
            "GITHUB_OUTPUT": str(self.root / "output"),
        }))

    def test_gate_attempt_records_safe_rejection(self):
        for error, expected in ((ValueError("open-dependency"), "open-dependency"),
                                (RuntimeError(SECRET), "control-failed")):
            with mock.patch.object(control, "gate", side_effect=error):
                with self.assertRaises(type(error)):
                    control.gate_attempt("1", str(self.out))
            self.assertIn(expected, (self.root / "summary").read_text())
            self.assertNotIn(SECRET, (self.root / "summary").read_text())

    def test_trusted_rejection_comments_without_changing_labels(self):
        with mock.patch.object(control, "status_comment") as comment:
            control.gate_feedback("1", "failure", "open-dependency")
        body = comment.call_args.args[1]
        self.assertIn("open-dependency", body)
        self.assertIn("Complete the declared dependencies", body)
        self.assertIn("actions/runs/123", body)
        self.assertEqual(self.calls, [f"repos/{REPO}/issues/1"])

    def test_unknown_reason_does_not_reach_comment(self):
        with mock.patch.object(control, "status_comment") as comment:
            control.gate_feedback("1", "failure", SECRET)
        self.assertIn("diagnostics-unavailable", comment.call_args.args[1])
        self.assertNotIn(SECRET, comment.call_args.args[1])

    def test_public_unrelated_and_wrong_ref_events_cannot_write(self):
        for patch in ({"GITHUB_ACTOR": "intruder"}, {"GITHUB_TRIGGERING_ACTOR": "intruder"},
                      {"GITHUB_REF": "refs/heads/feature"}, {"LABEL_NAME": "ready-for-agent"},
                      {"EVENT_NAME": "pull_request"}):
            with self.subTest(patch=patch), mock.patch.dict(os.environ, patch), mock.patch.object(control, "status_comment") as comment:
                control.gate_feedback("1", "failure", "open-dependency")
                comment.assert_not_called()
        self.issue["user"]["login"] = "intruder"
        with mock.patch.object(control, "status_comment") as comment:
            control.gate_feedback("1", "failure", "wrong-author")
            comment.assert_not_called()

    def test_status_comment_updates_only_bot_marker(self):
        marker = "<!-- factory-status:123 -->"
        public = {"id": 5, "user": {"login": "intruder"}, "body": marker}
        bot = {"id": 6, "user": {"login": "github-actions[bot]", "type": "Bot"}, "body": marker + "\nold"}
        for pages, method, path in (([[public]], "POST", f"issues/1/comments"),
                                    ([[public, bot]], "PATCH", "issues/comments/6")):
            with mock.patch.object(control.subprocess, "check_output", return_value=json.dumps(pages).encode()), mock.patch.object(control.subprocess, "run") as run:
                control.status_comment("1", "new")
            self.assertEqual(run.call_args.args[0][3:5], [method, f"repos/{REPO}/{path}"])
            self.assertEqual(json.loads(run.call_args.kwargs["input"])["body"], marker + "\nnew")

    def test_terminal_report_missing_artifacts_and_safe_check_detail(self):
        jobs = {name: {"result": "skipped", "outputs": {}} for name in
                ("claim", "handoff", "round1", "round2", "round3")}
        jobs["claim"]["result"] = "success"
        jobs["round1"]["result"] = "failure"
        with mock.patch.dict(os.environ, {"OUTCOMES": json.dumps(jobs)}), mock.patch.object(control.subprocess, "run"), mock.patch.object(control, "status_comment") as comment:
            control.terminal_report("1", str(self.out))
        self.assertIn("diagnostics-unavailable", comment.call_args.args[1])
        self.assertIn("Reason: round-failed", comment.call_args.args[1])
        self.assertIn("check-failed=lint", control.round_status({"verify": {"outputs": {"failed_check": "lint"}}}))
        self.assertNotIn(SECRET, control.round_status({"verify": {"outputs": {"failed_check": SECRET}}}))

    def test_third_round_exhausts_the_shared_budget(self):
        for outcome, reason in (("checks_failed", "checks-exhausted"),
                                ("request_changes", "rework-exhausted")):
            jobs = {name: {"result": "success", "outputs": {}} for name in
                    ("claim", "round1", "round2", "round3", "handoff")}
            jobs["handoff"]["result"] = "skipped"
            jobs["round3"]["outputs"]["outcome"] = outcome
            with mock.patch.dict(os.environ, {"OUTCOMES": json.dumps(jobs)}), \
                    mock.patch.object(control.subprocess, "run"), \
                    mock.patch.object(control, "status_comment") as comment:
                control.terminal_report("1", str(self.out))
            self.assertIn(f"Reason: {reason}", comment.call_args.args[1])

    def test_round_states_preserve_success_and_explicit_not_started(self):
        jobs = {"implement": {"result": "success"}, "verify": {"result": "success"},
                "review": {"result": "failure", "outputs": {"standards": "timeout"}}}
        text = control.round_status(jobs)
        for part in ("implement=success", "verify=success", "standards=timeout", "spec=not-started"):
            self.assertIn(part, text)
        jobs["review"]["outputs"] = {"standards": SECRET}
        text = control.round_status(jobs)
        self.assertIn("spec=unavailable", text)
        self.assertNotIn(SECRET, text)


class ClaimedTest(GateTest):
    def setUp(self):
        super().setUp()
        authorization.gate("1", str(self.out))
        self.issue["labels"] = [{"name": name} for name in ("ready-for-agent", "implementing")]
        self.event = {**labeled("labeled", "github-actions[bot]", "implementing"), "id": 987}
        self.pages = [[labeled("labeled", OWNER)], [self.event]]
        self.enterContext(mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}))
        self.record = self.root / "claim.json"
        self.calls.clear()

    # GateTest's cases also exercise the shared validation against claimed state.
    def gate(self):
        authorization.validate_issue("1", claimed=True, captured=authorization.snapshot("1", str(self.out)))

    def test_accepts_authorized_issue_and_writes_body(self):
        authorization.record_claim("1", str(self.out), str(self.record))
        authorization.claimed("1", str(self.out), str(self.record))
        record = json.loads(self.record.read_text())
        self.assertEqual(record, {"issue": "1", "repository": REPO, "run_id": "123",
                                  "run_attempt": "1", "event_id": 987,
                                  "snapshot": authorization.snapshot("1", str(self.out))})

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

    def test_native_dependency_summary_blocks_gate(self):
        self.issue["issue_dependencies_summary"] = {"blocked_by": 1}
        self.gate()  # After claim, the captured dependencies remain authoritative.

    def test_claim_detects_race_but_later_edits_do_not_change_spec(self):
        original = self.issue["body"]
        self.issue["body"] += " changed"
        self.assertRejects("body-changed", control.record_claim, "1", str(self.out), str(self.record))
        self.issue["body"] = original
        authorization.record_claim("1", str(self.out), str(self.record))
        self.issue["body"] = "Entirely new spec. Blocked by #99"
        authorization.claimed("1", str(self.out), str(self.record))
        self.assertEqual((self.out / "issue.md").read_text(), original)

    def test_gate_captures_any_current_body_without_manual_config(self):
        pass  # Gate capture is tested before the claim in GateTest.

    def test_issue_ten_needs_no_task_file(self):
        pass

    def test_rejects_stale_run_attempt_repository_issue_and_event(self):
        authorization.record_claim("1", str(self.out), str(self.record))
        original = self.record.read_text()
        for key, value in (("run_id", "999"), ("run_attempt", "2"), ("repository", "other/repo"),
                           ("issue", "2"), ("event_id", 988)):
            with self.subTest(key=key):
                data = json.loads(original)
                data[key] = value
                self.record.write_text(json.dumps(data))
                self.assertRejects("stale-claim", control.claimed, "1", str(self.out), str(self.record))
        self.record.write_text(original)
        self.event["id"] = 989
        self.assertRejects("stale-claim", control.claimed, "1", str(self.out), str(self.record))

    def test_rejects_claim_event_without_valid_id(self):
        for value in (None, "987", True, 0):
            with self.subTest(value=value):
                self.event["id"] = value
                self.assertRejects("invalid-claim-event", control.record_claim, "1", str(self.out), str(self.record))
        self.assertFalse(self.record.exists())


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.auth = self.directory / "auth.json"
        self.auth.write_text(json.dumps({"provider": {"type": "api", "key": "Zq9/\"opaque+cred",
                                                       "short": "abc"}}))
        self.enterContext(mock.patch.dict(os.environ, {"FACTORY_AUTH_FILE": str(self.auth)}))

    def artifact(self, content):
        path = self.directory / "artifact"
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        return str(path)

    def assertRejects(self, reason, content):
        with self.assertRaises(ValueError) as caught:
            artifacts.scan(self.artifact(content))
        self.assertEqual(str(caught.exception), reason)

    def test_accepts_clean_artifact(self):
        artifacts.scan(self.artifact("diff --git a/x b/x\n+const task-assessment-for-merged-private = 1\n"
                                   "+// abc api key handling\n"))

    def test_accepts_without_auth_file(self):
        with mock.patch.dict(os.environ):
            del os.environ["FACTORY_AUTH_FILE"]
            with self.assertRaisesRegex(ValueError, "^missing-auth-file$"):
                artifacts.scan(self.artifact("Zq9/\"opaque+cred"))
            artifacts.scan(self.artifact("Zq9/\"opaque+cred"), public=True)
            with self.assertRaisesRegex(ValueError, "^credential-pattern-in-artifact$"):
                artifacts.scan(self.artifact(SECRET), public=True)

    def test_rejects_exact_credential(self):
        self.assertRejects("credential-in-artifact", 'leak Zq9/"opaque+cred here')

    def test_rejects_json_escaped_credential(self):
        event = json.dumps({"type": "text", "part": {"text": 'Zq9/"opaque+cred'}})
        self.assertRejects("credential-in-artifact", event)

    def test_ignores_short_values(self):
        artifacts.scan(self.artifact("abc api"))

    def test_rejects_credential_patterns(self):
        for content in ("ghp_" + "a" * 36, "token=gho_" + "B" * 20, "github_pat_" + "c_" * 15,
                        SECRET, "(sk-" + "d" * 20 + ")",
                        "-----BEGIN OPENSSH PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----"):
            with self.subTest(content=content[:12]):
                self.assertRejects("credential-pattern-in-artifact", content)

    def test_rejects_oversized_artifact(self):
        self.assertRejects("artifact-too-large", b"a" * (artifacts.MAX_ARTIFACT_BYTES + 1))

    def test_accepts_artifact_at_size_limit(self):
        artifacts.scan(self.artifact(b"a" * artifacts.MAX_ARTIFACT_BYTES))

    def test_unlimited_scan_accepts_any_size_but_still_finds_credentials(self):
        large = "检查🙂 é\n" * (artifacts.MAX_ARTIFACT_BYTES // 4)
        self.assertGreater(len(large.encode()), artifacts.MAX_ARTIFACT_BYTES)
        artifacts.scan(self.artifact(large), limit=None)
        artifacts.scan(self.artifact(large), public=True, limit=None)
        # A leak at the very end of a large artifact is still found.
        for leak, reason in ((SECRET, "credential-pattern-in-artifact"),
                             ('Zq9/"opaque+cred', "credential-in-artifact")):
            for public in (False, True):
                with self.subTest(reason=reason, public=public), \
                        self.assertRaisesRegex(ValueError, f"^{reason}$"):
                    artifacts.scan(self.artifact(large + leak), public=public, limit=None)
        with mock.patch.dict(os.environ):
            del os.environ["FACTORY_AUTH_FILE"]
            with self.assertRaisesRegex(ValueError, "^missing-auth-file$"):
                artifacts.scan(self.artifact(large), limit=None)

    def test_cli_scan_output_is_private_and_unlimited(self):
        def run(content, env):
            return subprocess.run([sys.executable, "-I", str(CONTROL), "scan-output", self.artifact(content)],
                                  capture_output=True, text=True, env=env)
        large = "ü" * artifacts.MAX_ARTIFACT_BYTES
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


def mixed_text(units):
    """Deterministic text mixing 1- to 4-byte UTF-8, joiners, mentions and whitespace runs."""
    pieces = ("a", "é", "检", "🙂", " @team", "  \t", "\n", "👩‍💻", "```", "\n\n")
    return "".join(pieces[(index * 7 + index // 3) % len(pieces)] for index in range(units))


class CommentsTest(unittest.TestCase):
    RUN = f"https://github.com/{REPO}/actions/runs/123"

    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.reports = self.directory / "reports"
        self.output = self.directory / "comments"
        auth = self.directory / "auth.json"
        auth.write_text(json.dumps({"key": "opaque-credential-value"}))
        self.enterContext(mock.patch.dict(os.environ, {
            "GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": "123", "FACTORY_AUTH_FILE": str(auth)}))

    def write(self, name, content):
        path = self.reports / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def comments(self):
        control.comments(str(self.reports), str(self.output))
        # The workflow posts bodies in shell glob order, so that order must be the reading order.
        return [path.read_bytes() for path in sorted(self.output.glob("*.md"))] if self.output.exists() else []

    def documents(self, bodies):
        """Group parts by report, checking Part i/n numbering, and rejoin each report's chunks."""
        documents = []
        for body in bodies:
            self.assertLessEqual(len(body), 60_000)
            match = re.fullmatch(r"(.*?)Part (\d+)/(\d+)\n\n(.*)", body.decode(), re.DOTALL)
            self.assertIsNotNone(match, body[:200])
            preface, part, total, chunk = match[1], int(match[2]), int(match[3]), match[4]
            if part == 1:
                documents.append({"preface": preface, "total": total, "parts": 0, "text": ""})
            document = documents[-1]
            self.assertEqual((preface, total, part), (document["preface"], document["total"], document["parts"] + 1))
            document["parts"] += 1
            document["text"] += chunk
        for document in documents:
            self.assertEqual(document["parts"], document["total"])
            self.assertIn(self.RUN, document["preface"])
        return documents

    def test_publishes_present_reports_in_round_order(self):
        self.write("feedback-3/review.json", json.dumps({"findings": [], "advisory": ["Spec: improve naming"]}))
        self.write("feedback-1/review.json", json.dumps({"findings": ["Standards: fix scope"], "advisory": []}))
        self.write("feedback-2/checks.json", '{"command": "pnpm test", "output": "boom"}')
        documents = self.documents(self.comments())
        self.assertEqual([document["text"] for document in documents], [
            "### Findings\n\n- **Blocking** — Standards: fix scope\n",
            "### Findings\n\n- Advisory — Spec: improve naming\n"])
        for document, label in zip(documents, ("round 1", "round 3")):
            with self.subTest(label=label):
                self.assertIn(label, document["preface"].lower())
        self.assertNotIn("pnpm test", "".join(document["text"] for document in documents))

    def test_no_reports_write_no_comments(self):
        self.assertEqual(self.comments(), [])
        self.reports.mkdir()
        self.write("feedback-1/checks.json", "{}")
        self.assertEqual(self.comments(), [])

    def test_large_unicode_reports_split_within_limit_and_reassemble_exactly(self):
        review = mixed_text(250_000)
        self.write("feedback-2/review.json", json.dumps({"findings": [], "advisory": [review]}))
        bodies = self.comments()
        self.assertEqual(control.COMMENT_BYTES, 60_000)
        # More than nine parts, so glob order has to keep numeric order.
        self.assertGreater(len(bodies), 10)
        for body in bodies:
            body.decode("utf-8")  # Never splits inside a character.
        documents = self.documents(bodies)
        self.assertEqual([document["text"] for document in documents],
                         ["### Findings\n\n- Advisory \u2014 " + review.replace("@", "@\u200b") + "\n"])
        self.assertGreater(documents[0]["total"], 1)

    def test_refuses_credentials_anywhere_in_large_reports(self):
        text = mixed_text(30_000)
        boundary = len(text.encode()[:59_000].decode(errors="ignore"))
        straddling = text[:boundary - 10] + f" {SECRET} " + text[boundary - 10:]
        for name, content, reason in (
            ("feedback-1/review.json", json.dumps({"findings": [], "advisory": [straddling]}), "credential-pattern-in-artifact"),
            ("feedback-4/review.json", json.dumps({"findings": [text * 3 + " " + SECRET], "advisory": []}), "credential-pattern-in-artifact"),
            ("feedback-2/review.json", json.dumps({"findings": [], "advisory": [text * 3 + "opaque-credential-value"]}), "credential-in-artifact"),
        ):
            with self.subTest(name=name, reason=reason):
                shutil.rmtree(self.reports, ignore_errors=True)
                self.write(name, content)
                with self.assertRaisesRegex(ValueError, f"^{reason}$"):
                    self.comments()

    def test_cli_writes_comments_and_hides_credentials(self):
        self.write("feedback-1/review.json", json.dumps({"findings": ["fine"], "advisory": []}))
        args = [sys.executable, "-I", str(CONTROL), "comments", str(self.reports), str(self.output)]
        result = subprocess.run(args, capture_output=True, text=True, env={**os.environ})
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(self.documents([path.read_bytes() for path in sorted(self.output.glob("*.md"))])[0]["text"],
                         "### Findings\n\n- **Blocking** — fine\n")
        self.write("feedback-1/review.json", json.dumps({"findings": [f"x {SECRET}"], "advisory": []}))
        result = subprocess.run(args, capture_output=True, text=True, env={**os.environ})
        self.assertEqual((result.returncode, result.stderr), (1, "::error::credential-pattern-in-artifact\n"))
        self.assertNotIn(SECRET, result.stdout)


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


class RunnerStepTest(unittest.TestCase):
    """Run real supervised workflow steps against a stub Claude Code binary."""

    jobs = {"implement": ("software-factory-round.yml", "implement"),
            "review": ("software-factory-round.yml", "review"),
            "publish": ("software-factory-implement.yml", "publish-reviews")}

    def run_step(self, job, claude="exit 0", gh="exit 0", select=None, env=None, files=None, setup=None,
                 budget="5"):
        select = select or {"implement": "Generate bounded candidate",
                            "review": "Independently review verified candidate"}.get(job, "claude -p")
        workflow, name = self.jobs[job]
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.directory = directory
        (directory / "trusted").symlink_to(CONTROL.parents[2])
        (directory / ".github").symlink_to(CONTROL.parents[2] / ".github")
        (directory / "candidate").mkdir()
        (directory / "workspace").mkdir()
        bin_dir = directory / "bin"
        bin_dir.mkdir()
        log = 'printf "%s\\0" "${0##*/}" "$@" > "$CALLS/$(printf %03d $(($(ls "$CALLS" | wc -l))))"\n'
        for program, script in (("gh", gh), ("claude", claude)):
            (bin_dir / program).write_text(f"#!/bin/bash\n{log}{script}\n")
            (bin_dir / program).chmod(0o755)
        (directory / "calls").mkdir()
        auth = directory / "auth.json"
        auth.write_text(json.dumps({"key": SECRET}))
        (directory / "temp/input").mkdir(parents=True)
        for filename, content in (files or {}).items():
            (directory / filename).parent.mkdir(parents=True, exist_ok=True)
            (directory / filename).write_text(content)
        if setup:
            setup(directory)
        steps = WorkflowContractTest.load(workflow)["jobs"][name]["steps"]
        step = next(step for step in steps if select in step.get("run", "") or select == step.get("name"))
        cwd = directory / step["working-directory"] if "working-directory" in step else directory
        env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "ISSUE": "6", "ROUND": "1",
               "RUNNER_TEMP": str(directory / "temp"), "FACTORY_AUTH_FILE": str(auth),
               "GITHUB_OUTPUT": str(directory / "output"), "GITHUB_STEP_SUMMARY": str(directory / "summary"),
               "GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": "123", "GITHUB_WORKSPACE": str(directory),
               "CALLS": str(directory / "calls"), "ANTHROPIC_MODEL": "deepseek-flash",
               "CLAUDE_CONFIG_DIR": str(directory / "temp/claude-config"), "CLAUDE_SETTINGS": "settings.json",
               "REVIEW_OUTPUT": str(directory / "temp/feedback/review.json"), **(env or {})}
        script = re.sub(r' (600|1500) --', f' {budget} --', step["run"])
        result = subprocess.run(["bash", "-e", "-c", script], cwd=cwd, env=env,
                                capture_output=True, text=True, timeout=30)
        return result, (directory / "summary").read_text() if (directory / "summary").exists() else ""

    def calls(self, program):
        calls = [path.read_text().split("\0")[:-1] for path in sorted((self.directory / "calls").iterdir())]
        return [call[1:] for call in calls if call[0] == program]

    def result(self, **event):
        return "echo '" + json.dumps({"type": "result", "subtype": "success", "is_error": False, **event}) + "'"

    def reply(self, value):
        return self.result(structured_output=value)

    def test_timeout_is_summarized_and_preserved_without_leaking(self):
        for job in ("implement", "review"):
            with self.subTest(job=job):
                result, summary = self.run_step(job, f"echo {SECRET} >&2\nexec sleep 20", budget="1")
                self.assertEqual(result.returncode, 124, result.stderr)
                self.assertIn('"exit_status": 124', result.stdout)
                self.assertIn("### Factory Agent run", summary)
                self.assertIn("::error::standards-timeout" if job == "review" else "::error::claude-exit-124",
                              result.stdout)
                self.assertNotIn(SECRET, result.stdout + result.stderr + summary)
                self.assertEqual(len(self.calls("claude")), 1)

    def test_review_runner_error_stops_spec_and_retains_exit(self):
        result, _ = self.run_step("review", "exit 3")
        self.assertEqual(result.returncode, 3)
        self.assertEqual((self.directory / "output").read_text(), "standards=started\nstandards=runner-error\n")
        self.assertEqual(len(self.calls("claude")), 1)

    def test_canary_rejects_a_missing_shell_result(self):
        for shell, status in ((False, 1), (True, 0)):
            stub = 'printf ok > canary-write\n'
            if shell:
                stub += 'printf ok > canary-shell\n'
            stub += self.reply({"findings": []})
            result, _ = self.run_step("implement", stub, select="Verify candidate configuration is inert")
            self.assertEqual(result.returncode, status, result.stderr)

    def test_implement_validates_native_result(self):
        result, _ = self.run_step("implement", self.result(result="Done."))
        self.assertEqual(result.returncode, 0, result.stderr)
        result, _ = self.run_step("implement", "echo '" + json.dumps(
            {"type": "result", "subtype": "success", "is_error": True, "result": "failed"}) + "'")
        self.assertEqual(result.returncode, 1)
        self.assertIn("::error::provider-error", result.stderr)

    def test_review_runs_each_axis_in_its_own_session(self):
        result, summary = self.run_step("review", self.reply(
            {"findings": [{"blocking": False, "finding": "src/a.ts: possible Mysterious Name"}]}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(summary.count("### Factory Agent run"), 2)
        sessions = self.calls("claude")
        self.assertEqual(len(sessions), 2)
        axes = control.review_axes()
        expected = json.loads(json.dumps(control.FINDINGS_SCHEMA))
        ids = []
        for (axis, other), session in zip((("standards", "spec"), ("spec", "standards")), sessions):
            with self.subTest(axis=axis):
                self.assertIn("--bare", session)
                self.assertIn("--restricted", session)
                self.assertEqual(session[session.index("--output-format") + 1], "json")
                self.assertEqual(session[session.index("--json-schema") + 1],
                                 json.dumps(expected, separators=(",", ":")))
                self.assertIn(axes[axis]["brief"], session[-1])
                self.assertNotIn(axes[other]["brief"], session[-1])
                ids.append(session[session.index("--session-id") + 1])
                self.assertTrue((self.directory / f"temp/review-{axis}.json").is_file())
        self.assertNotEqual(*ids)
        self.assertEqual((self.directory / "output").read_text(),
                         "standards=started\nstandards=passed\nspec=started\nspec=passed\nverify=skipped\nverdict=approve\n")
        review = json.loads((self.directory / "temp/feedback/review.json").read_text())
        self.assertEqual(review["advisory"], ["Standards: src/a.ts: possible Mysterious Name",
                                              "Spec: src/a.ts: possible Mysterious Name"])
        self.assertFalse((self.directory / "temp/feedback/review.md").exists())

    def test_blocking_findings_require_a_covering_verifier(self):
        claude = ('if [[ "$*" == *\'"verdicts"\'* ]]; then\n'
                  + self.reply({"verdicts": [{"id": 0, "confirmed": False, "evidence": "old code"},
                                              {"id": 1, "confirmed": True, "evidence": "a.ts:4"}]})
                  + '\nelse\n' + self.reply({"findings": [{"blocking": True, "finding": "bug",
                                                           "path": "a.ts", "line": 4}]}) + '\nfi')
        result, _ = self.run_step("review", claude, files={"candidate/.factory-input/issue.md": "spec"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls("claude")), 3)
        review = json.loads((self.directory / "temp/feedback/review.json").read_text())
        self.assertEqual(review["findings"], ["Spec: bug"])
        self.assertEqual(len(review["advisory"]), 1)
        self.assertIn("Unconfirmed by verification: old code", review["advisory"][0])
        claims = json.loads((self.directory / "candidate/.factory-input/blocking.json").read_text())
        self.assertEqual([item["id"] for item in claims], [0, 1])
        self.assertEqual([item["finding"] for item in claims], ["bug", "bug"])
        self.assertTrue(all(item["path"] == "a.ts" and item["line"] == 4 for item in claims))
        self.assertIn("verify=started\nverify=passed\n", (self.directory / "output").read_text())

    def test_verifier_failure_fails_closed_without_a_report(self):
        claude = ('if [[ "$*" == *\'"verdicts"\'* ]]; then exit 3; fi\n'
                  + self.reply({"findings": [{"blocking": True, "finding": "bug",
                                              "path": "a.ts", "line": 4}]}))
        result, _ = self.run_step("review", claude, files={"candidate/.factory-input/issue.md": "spec"})
        self.assertEqual(result.returncode, 3)
        self.assertIn("verify=runner-error", (self.directory / "output").read_text())
        self.assertFalse((self.directory / "temp/feedback/review.json").exists())

    def test_verifier_rejects_incomplete_verdicts(self):
        claude = ('if [[ "$*" == *\'"verdicts"\'* ]]; then\n'
                  + self.reply({"verdicts": []}) + '\nelse\n'
                  + self.reply({"findings": [{"blocking": True, "finding": "bug",
                                              "path": "a.ts", "line": 4}]}) + '\nfi')
        result, _ = self.run_step("review", claude, files={"candidate/.factory-input/issue.md": "spec"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("verify=invalid-output", (self.directory / "output").read_text())
        self.assertFalse((self.directory / "temp/feedback/review.json").exists())

    def test_repair_round_prompt_receives_incremental_context(self):
        result, _ = self.run_step("review", self.reply({"findings": []}), env={"REPAIR": "true"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all("repair.patch" in call[-1] for call in self.calls("claude")))

    def test_review_accepts_output_beyond_the_artifact_limit(self):
        finding = {"blocking": False, "finding": "src/a.ts: " + "说明 " * 100_000}
        result, _ = self.run_step("review", 'cat "$CALLS/../reply.json"', files={
            "reply.json": json.dumps({"type": "result", "subtype": "success", "is_error": False,
                                      "structured_output": {"findings": [finding]}})})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater((self.directory / "temp/feedback/review.json").stat().st_size, artifacts.MAX_ARTIFACT_BYTES)

    def test_review_rejects_old_schema(self):
        result, _ = self.run_step("review", self.reply({"verdict": "approve", "findings": []}))
        self.assertEqual(result.returncode, 1)
        self.assertIn("::error::invalid-review", result.stderr)
        self.assertEqual((self.directory / "output").read_text(), "standards=started\nstandards=invalid-output\n")

    def test_sessions_are_native_unmodified_and_scanned(self):
        session_id = "123e4567-e89b-42d3-a456-426614174000"
        for job, names in (("implement", ["implementation"]),
                           ("review", ["review-standards", "review-spec"])):
            with self.subTest(job=job):
                files = {f"temp/{name}.session": session_id for name in names}
                source = f"temp/claude-config/projects/factory/{session_id}.jsonl"
                files[source] = '{"message":"native"}\n{"tool":"Read"}\n'
                result, _ = self.run_step(job, select="control.py claude-transcript", files=files)
                self.assertEqual(result.returncode, 0, result.stderr)
                saved = list((self.directory / "temp/session").iterdir())
                self.assertEqual(len(saved), len(names))
                self.assertTrue(all(path.read_text() == files[source] for path in saved))
                self.assertEqual(len(self.uploaded(job)), len(names))
                files[source] = json.dumps({"text": SECRET}) + "\n"
                result, _ = self.run_step(job, select="control.py claude-transcript", files=files)
                self.assertEqual(result.returncode, 1)
                self.assertIn("::error::credential-in-artifact", result.stderr)
                self.assertNotIn(SECRET, result.stdout + result.stderr)

    def uploaded(self, job):
        workflow, name = self.jobs[job]
        upload = next(step for step in WorkflowContractTest.load(workflow)["jobs"][name]["steps"]
                      if str(step.get("with", {}).get("name", "")).startswith("session-"))
        paths = (Path(line.replace("${{ runner.temp }}", str(self.directory / "temp"))
                      .replace("${{ inputs.round }}", "1")) for line in upload["with"]["path"].splitlines())
        return [file.name for path in paths for file in [path] if file.is_file()]

    def publish(self, reports, pr=""):
        gh = (f'if [ "$1 $2" = "pr list" ]; then printf %s "{pr}"; fi\n'
              'if [ "$2" = comment ]; then mkdir -p "$CALLS/../bodies"\n'
              '  cp "$5" "$CALLS/../bodies/$(printf %03d $(ls "$CALLS" | wc -l))"; fi')
        result, _ = self.run_step("publish", gh=gh, select="control.py comments", env={"FACTORY_AUTH_FILE": ""},
                                  files={f"temp/reports/{name}": content for name, content in reports.items()})
        bodies = self.directory / "bodies"
        return result, [path.read_bytes() for path in sorted(bodies.iterdir())] if bodies.exists() else []

    def test_review_publish_comments_every_report_on_open_pr_else_issue(self):
        reports = {"feedback-1/review.json": json.dumps({"findings": ["Standards: bug"], "advisory": ["ping @maintainer"]}),
                   "feedback-2/checks.json": "{}"}
        for pr, target in (("17", ["pr", "comment", "17"]), ("", ["issue", "comment", "6"])):
            with self.subTest(pr=pr):
                result, bodies = self.publish(reports, pr)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = self.calls("gh")
                self.assertEqual([call[:2] for call in calls], [["pr", "list"], target[:2]])
                self.assertTrue(all(call[:3] == target for call in calls[1:]))
                self.assertEqual(len(bodies), 1)
                self.assertIn("Standards: bug", bodies[0].decode())
                self.assertIn("ping @\u200bmaintainer", bodies[0].decode())

    def test_review_publish_posts_whatever_reports_exist(self):
        empty = json.dumps({"findings": [], "advisory": []})
        for reports, count in (({"feedback-1/review.json": empty, "feedback-3/review.json": empty}, 2),
                               ({"feedback-1/checks.json": "{}"}, 0), ({}, 0)):
            with self.subTest(reports=list(reports)):
                result, bodies = self.publish(reports, "17")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(bodies), count)

    def test_review_publish_splits_large_output_in_order(self):
        review = mixed_text(80_000)
        result, bodies = self.publish({"feedback-1/review.json": json.dumps({"findings": [], "advisory": [review]})}, "17")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(len(bodies), 1)
        self.assertTrue(all(len(body) <= 60_000 for body in bodies))
        chunks = [re.fullmatch(r"(.*?)Part (\d+)/(\d+)\n\n(.*)", body.decode(), re.DOTALL) for body in bodies]
        self.assertEqual("".join(match[4] for match in chunks),
                         ("### Findings\n\n- Advisory \u2014 " + review + "\n").replace("@", "@\u200b"))

    def test_review_publish_refuses_credentials(self):
        for reports in ({"feedback-1/review.json": json.dumps({"findings": [], "advisory": [SECRET]})},
                        {"feedback-2/review.json": json.dumps({"findings": [f"leak {SECRET}"], "advisory": []})}):
            with self.subTest(reports=list(reports)):
                result, bodies = self.publish(reports, "17")
                self.assertEqual(result.returncode, 1)
                self.assertIn("::error::credential-pattern-in-artifact", result.stderr)
                self.assertNotIn(SECRET, result.stdout + result.stderr)
                self.assertEqual((self.calls("gh"), bodies), ([], []))


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

    def test_validation_and_handoff_do_not_receive_provider_configuration(self):
            validating = [step for step in self.steps()
                          if re.search(r"control\.py (gate-attempt|revalidate|record-claim|claimed) ", step.get("run", ""))]
            self.assertEqual(len(validating), 4)
            for step in validating:
                with self.subTest(step=step.get("name")):
                    self.assertNotIn("ANTHROPIC", str(step))
                    self.assertNotIn("secrets.", str(step))

    def test_failure_diagnostics_do_not_require_success_or_model_artifacts(self):
        jobs = self.implement["jobs"]
        self.assertIn("always()", jobs["gate-feedback"]["if"])
        self.assertNotIn("== 'success'", jobs["gate-feedback"]["if"])
        self.assertIn("github.actor == github.repository_owner", jobs["gate-feedback"]["if"])
        self.assertEqual(jobs["gate"]["outputs"]["reason"], "${{ steps.validation.outputs.reason }}")
        diagnostics = self.round["jobs"]["diagnostics"]
        self.assertEqual(diagnostics["if"], "always()")
        self.assertNotIn("secrets", str(diagnostics))
        self.assertNotIn("download-artifact", str(diagnostics))
        self.assertIn("inputs.base", str(diagnostics))

    def test_round_callers_explicitly_pass_the_environment_secret(self):
        trigger = self.round.get("on", self.round.get(True))
        self.assertEqual(trigger["workflow_call"].get("secrets"), {
            "AGENT_API_KEY": {"required": True},
        })
        for name in ("round1", "round2", "round3"):
            with self.subTest(round=name):
                self.assertEqual(self.implement["jobs"][name].get("secrets"), {
                    "AGENT_API_KEY": "${{ secrets.AGENT_API_KEY }}",
                })
        for name, job in self.round["jobs"].items():
            with self.subTest(job=name):
                if name in ("implement", "review"):
                    self.assertEqual(job["environment"], "agent")
                else:
                    self.assertNotIn("environment", job)
                    self.assertNotIn("secrets", str(job))

    def test_repairable_outcomes_reach_every_later_round(self):
        jobs = self.implement["jobs"]
        rounds = sorted(name for name in jobs if name.startswith("round"))
        self.assertEqual(rounds, ["round1", "round2", "round3"])
        for previous, current in zip(rounds, rounds[1:]):
            with self.subTest(round=current):
                self.assertEqual(jobs[current]["needs"], previous)
                for outcome in ("checks_failed", "request_changes"):
                    self.assertIn(f"needs.{previous}.outputs.outcome == '{outcome}'", jobs[current]["if"])
        for job in ("handoff", "report"):
            self.assertLessEqual(set(rounds), set(jobs[job]["needs"]))
        self.assertIn("toJSON(needs)", str(jobs["report"]))

    def test_checked_patch_is_uploaded_before_candidate_code_runs(self):
        steps = self.round["jobs"]["verify"]["steps"]
        upload = next(index for index, step in enumerate(steps)
                      if step.get("with", {}).get("name") == "checked-${{ inputs.round }}")
        for index, step in enumerate(steps):
            if re.search(r"verification.py (lint|typecheck|build:admin|test)", step.get("run", "")):
                self.assertGreater(index, upload, step["run"])
        self.assertNotIn("secrets", str(self.round["jobs"]["verify"]))

    def test_verification_identity_failure_stops_repair_and_review(self):
        steps = self.round["jobs"]["verify"]["steps"]
        reject = next(i for i, step in enumerate(steps) if "verification.py assert" in step.get("run", ""))
        feedback = next(i for i, step in enumerate(steps) if "control.py diagnose" in step.get("run", ""))
        self.assertLess(reject, feedback)
        self.assertNotIn("continue-on-error", steps[reject])
        self.assertNotIn("if", steps[reject])
        self.assertIn('"$VERIFICATION_FAILURE"', steps[reject]["run"])
        self.assertIn("VERIFICATION_FAILURE=", str(steps[:reject]))
        self.assertEqual(steps[reject]["id"], "integrity")
        checks = self.round["jobs"]["verify"]["outputs"]["checks"]
        self.assertIn("steps.integrity.outcome == 'success'", checks)
        self.assertTrue(checks.endswith("|| '' }}"))

    def test_shared_files_contain_no_task_specific_text(self):
        shared = [*(CONTROL.parent / "prompts").glob("*.md"),
                  *(CONTROL.parents[2] / ".github/workflows").glob("software-factory-*.yml")]
        for path in shared:
            text = path.read_text()
            for fragment in ("merge consecutive private messages", "2.5", "batch"):
                with self.subTest(path=path.name, fragment=fragment):
                    self.assertNotIn(fragment, text)

    def test_review_repair_and_handoff_use_the_checked_patch(self):
        def downloads(job):
            return {step["with"].get("name", step["with"].get("pattern")) for step in job["steps"]
                    if "download-artifact" in step.get("uses", "")}
        jobs = self.round["jobs"]
        self.assertEqual(downloads(jobs["review"]), {
            "factory-input", "checked-${{ inputs.round }}", "feedback-*", "checked-*"})
        self.assertEqual(downloads(jobs["implement"]), {
            "factory-input", "checked-${{ steps.previous.outputs.round }}",
            "feedback-${{ steps.previous.outputs.round }}"})
        # Findings reach the PR as publish-reviews comments, never through the PR body.
        handoff = self.implement["jobs"]["handoff"]
        self.assertEqual(downloads(handoff), {"checked-${{ steps.approved.outputs.round }}", "factory-claim", "factory-input"})
        self.assertNotIn("advisory", str(handoff))
        self.assertNotIn("review.json", str(handoff))

    def test_handoff_uses_trusted_pr_skill_for_the_body(self):
        step = next(step for step in self.implement["jobs"]["handoff"]["steps"]
                    if step.get("id") == "pr")
        self.assertIn('control.py pr-body "$ISSUE" "$ROUND" "$RUNNER_TEMP/pr.md"', step["run"])
        self.assertEqual(step["env"]["ROUND"], "${{ steps.approved.outputs.round }}")
        self.assertNotIn("gh pr create", step["run"].split("control.py pr-body")[0])
        self.assertNotRegex(step["run"], r"printf .*Implements")

    def test_handoff_uses_trusted_control_after_patch_with_write_token(self):
        steps = self.implement["jobs"]["handoff"]["steps"]
        checkouts = [step["with"] for step in steps if "actions/checkout@" in step.get("uses", "")]
        self.assertEqual({item["path"] for item in checkouts}, {"trusted", "candidate"})
        for step in steps:
            if "control.py" in step.get("run", ""):
                self.assertEqual(step["working-directory"], "candidate")
                self.assertNotRegex(step["run"], r"python3 -I \.github/")
                self.assertIn("../trusted/.github/software-factory/control.py", step["run"])

    def test_snapshot_is_restored_after_repair_and_review_patch(self):
        for name in ("implement", "review"):
            steps = self.round["jobs"][name]["steps"]
            self.assertTrue(any("git apply" in step.get("run", "") for step in steps))
            restore = next(i for i, step in enumerate(steps) if 'cp -R "$RUNNER_TEMP/input"' in step.get("run", ""))
            if name == "implement":
                self.assertEqual(steps[restore]["env"]["ROUND"], "${{ inputs.round }}")
                install = next(i for i, step in enumerate(steps) if "pnpm install" in step.get("run", ""))
                self.assertLess(install, restore)

    def test_implement_canary_exercises_writes_without_project_configuration(self):
        steps = self.round["jobs"]["implement"]["steps"]
        canary = next(step["run"] for step in steps if step.get("name") == "Verify candidate configuration is inert")
        generation = self.claude_steps()["implement"]["run"]
        for forbidden in ("--dangerously-skip-permissions", "bypassPermissions"):
            self.assertNotIn(forbidden, canary + generation)
        self.assertIn('agent_runner.py" canary implement 120 --', canary)
        self.assertIn("Use Write to create canary-write", canary)
        self.assertIn("then Edit to replace initial with ok", canary)
        self.assertIn("Use Bash to test that canary-write contains ok", canary)
        self.assertIn('test "$(< "$canary/canary-write")" = ok', canary)
        self.assertIn("test ! -e \"$canary/hook-ran\" && test ! -e \"$canary/mcp-ran\"", canary)

    def test_review_uses_shared_runner_and_explicit_feedback_artifact(self):
        run = self.claude_steps()["review"]["run"]
        self.assertIn('agent_runner.py round 600 -- "$ISSUE"', run)
        self.assertNotIn("review.md", run)
        steps = self.round["jobs"]["review"]["steps"]
        upload = next(step["with"] for step in steps
                      if step.get("with", {}).get("name") == "feedback-${{ inputs.round }}")
        self.assertEqual(upload["path"], "${{ runner.temp }}/feedback")

    def jobs(self):
        for workflow in (self.implement, self.round):
            yield from workflow["jobs"].items()

    def claude_steps(self):
            return {name: step for name, job in self.jobs() for step in job.get("steps", [])
                    if re.search(r"agent_runner.py (implement|round) ", step.get("run", ""))}

    def test_model_deadlines(self):
        steps = self.claude_steps()
        self.assertEqual(set(steps), {"implement", "review"})
        self.assertIn("agent_runner.py implement 1500 --", steps["implement"]["run"])
        self.assertIn('agent_runner.py round 600 --', steps["review"]["run"])


    def test_only_implementation_gets_shell(self):
            modes = {name: re.findall(r"control\.py configure-claude \S+ (\w+)", step["run"])
                     for name, job in self.jobs() for step in job.get("steps", [])
                     if "control.py configure-claude" in step.get("run", "")}
            self.assertEqual(modes, {"implement": ["implement"], "review": ["review"]})
            self.assertIn("agent_runner.py implement", self.claude_steps()["implement"]["run"])
            self.assertIn("agent_runner.py round", self.claude_steps()["review"]["run"])
            self.assertNotIn("Write,Bash", self.claude_steps()["review"]["run"])

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
                    self.assertLess(run.index("control.py claude-transcript"), run.index("control.py scan-session"))
                    self.assertEqual(run.count("control.py claude-transcript"), 1)
                    self.assertEqual(run.count("control.py scan-session"), 1)
                    self.assertEqual(step["if"], "always() && steps.session.outcome == 'success'")
                    # Exact scanned files only, never the whole directory or a wildcard.
                    paths = step["with"]["path"].splitlines()
                    for path in paths:
                        self.assertTrue(path.startswith("${{ runner.temp }}/session/"), path)
                        self.assertTrue(path.endswith(".jsonl"), path)
                        self.assertNotIn("*", path)
                    self.assertEqual(step["with"]["retention-days"], 3)
        self.assertEqual(uploads, 2)

    def test_every_factory_artifact_expires_after_three_days(self):
        for name, job in self.jobs():
            for step in job.get("steps", []):
                if "upload-artifact" in step.get("uses", ""):
                    with self.subTest(job=name, artifact=step["with"]["name"]):
                        self.assertEqual(step["with"]["retention-days"], 3)

    def test_review_publish_holds_no_model_secret(self):
        publish = self.implement["jobs"]["publish-reviews"]
        self.assertEqual(set(publish["needs"]), {"claim", "round1", "round2", "round3", "handoff"})
        self.assertIn("always()", publish["if"])
        self.assertIn("needs.claim.result == 'success'", publish["if"])
        self.assertNotIn("secrets", str(publish))
        self.assertNotIn("ANTHROPIC", str(publish))
        self.assertEqual(publish["permissions"], {"contents": "read", "issues": "write", "pull-requests": "write"})
        downloads = [step for step in publish["steps"] if "download-artifact" in step.get("uses", "")]
        self.assertEqual([step["with"] for step in downloads], [
            {"pattern": "feedback-*", "path": "${{ runner.temp }}/reports"}])
        # A missing feedback artifact must not stop other reports from publishing.
        self.assertTrue(downloads[0].get("continue-on-error"))
        run = next(step["run"] for step in publish["steps"] if "gh " in step.get("run", ""))
        self.assertIn('control.py comments "$RUNNER_TEMP/reports"', run)
        self.assertLess(run.index("control.py comments"), run.index("gh "))
        self.assertIn("--body-file", run)


if __name__ == "__main__":
    unittest.main()
