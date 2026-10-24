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

    def test_retro_prompt_inlines_skill_closure(self):
        self.real_prompts()
        text = control.prompt("retro", "1")
        for name in ("prompts/retro.md", "skills/retro/SKILL.md", "skills/writing-for-agents/SKILL.md",
                     "skills/writing-for-agents/SKILL-MECHANICS.md"):
            with self.subTest(name=name):
                self.assertIn((CONTROL.parent / name).read_text(), text)
        self.assertNotIn("Build the thing.", text)

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
    return {"id": 456, "event": event, "actor": {"login": actor}, "label": {"name": name}}


class GateTest(TaskDirectory):
    def setUp(self):
        super().setUp()
        self.out = Path(self.enterContext(tempfile.TemporaryDirectory())) / "input"
        self.enterContext(mock.patch.dict(os.environ, {
            "GITHUB_REF": "refs/heads/main", "MODEL": control.MODEL, "GITHUB_REPOSITORY": REPO,
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
        self.enterContext(mock.patch.object(control, "api", self.fake_api))
        self.enterContext(mock.patch.object(control.subprocess, "check_output", self.fake_events))

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
        captured = control.snapshot("1", str(self.out))
        self.assertEqual(captured["blocked_by"], ["2"])
        self.assertEqual((self.out / "issue.md").read_text(), self.issue["body"])
        self.issue["body"] += " changed"
        self.assertRejects("body-changed", control.revalidate, "1", str(self.out))

    def test_crlf_snapshot_survives_gate_and_claim(self):
        self.issue["body"] = "Feature.\r\nBlocked by: #2\r\n"
        self.issue["labels"] = [{"name": n} for n in ("ready-for-agent", "agent:implement")]
        self.pages = [[labeled("labeled", OWNER)]]
        control.gate("1", str(self.out))
        control.revalidate("1", str(self.out))
        self.issue["labels"] = [{"name": n} for n in ("ready-for-agent", "implementing")]
        self.pages = [[{**labeled("labeled", "github-actions[bot]", "implementing"), "id": 987}]]
        control.record_claim("1", str(self.out), str(self.root / "claim.json"))
        self.assertEqual((self.out / "issue.md").read_bytes(), self.issue["body"].encode())

    def test_issue_ten_needs_no_task_file(self):
        with mock.patch.object(control, "api", side_effect=lambda path: self.issue if path.endswith("issues/10") else []), \
                mock.patch.object(control.subprocess, "check_output", return_value=json.dumps(self.pages).encode()):
            self.issue["body"] = "Feature without task JSON. Refs #99."
            control.gate("10", str(self.out))
        self.assertEqual(control.snapshot("10", str(self.out))["branch"], "feat/10-implement")

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
        self.assertEqual(control.dependencies(
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
        bot = {"id": 6, "user": {"login": "github-actions[bot]"}, "body": marker + "\nold"}
        for pages, method, path in (([[public]], "POST", f"issues/1/comments"),
                                    ([[public, bot]], "PATCH", "issues/comments/6")):
            with mock.patch.object(control.subprocess, "check_output", return_value=json.dumps(pages).encode()), mock.patch.object(control.subprocess, "run") as run:
                control.status_comment("1", "new")
            self.assertEqual(run.call_args.args[0][3:5], [method, f"repos/{REPO}/{path}"])
            self.assertEqual(json.loads(run.call_args.kwargs["input"])["body"], marker + "\nnew")

    def test_terminal_report_missing_artifacts_and_safe_check_detail(self):
        jobs = {name: {"result": "skipped", "outputs": {}} for name in
                ("claim", "handoff", "round1", "round2", "round3", "round4")}
        jobs["claim"]["result"] = "success"
        jobs["round1"]["result"] = "failure"
        with mock.patch.dict(os.environ, {"OUTCOMES": json.dumps(jobs)}), mock.patch.object(control.subprocess, "run"), mock.patch.object(control, "status_comment") as comment:
            control.terminal_report("1", str(self.out))
        self.assertIn("diagnostics-unavailable", comment.call_args.args[1])
        self.assertIn("Reason: round-failed", comment.call_args.args[1])
        self.assertIn("check-failed=lint", control.round_status({"verify": {"outputs": {"failed_check": "lint"}}}))
        self.assertNotIn(SECRET, control.round_status({"verify": {"outputs": {"failed_check": SECRET}}}))

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
        control.gate("1", str(self.out))
        self.issue["labels"] = [{"name": name} for name in ("ready-for-agent", "implementing")]
        self.event = {**labeled("labeled", "github-actions[bot]", "implementing"), "id": 987}
        self.pages = [[labeled("labeled", OWNER)], [self.event]]
        self.enterContext(mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}))
        self.record = self.root / "claim.json"
        self.calls.clear()

    # GateTest's cases also exercise the shared validation against claimed state.
    def gate(self):
        control.validate_issue("1", claimed=True, captured=control.snapshot("1", str(self.out)))

    def test_accepts_authorized_issue_and_writes_body(self):
        control.record_claim("1", str(self.out), str(self.record))
        control.claimed("1", str(self.out), str(self.record))
        record = json.loads(self.record.read_text())
        self.assertEqual(record, {"issue": "1", "repository": REPO, "run_id": "123",
                                  "run_attempt": "1", "event_id": 987,
                                  "snapshot": control.snapshot("1", str(self.out))})

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
        control.record_claim("1", str(self.out), str(self.record))
        self.issue["body"] = "Entirely new spec. Blocked by #99"
        control.claimed("1", str(self.out), str(self.record))
        self.assertEqual((self.out / "issue.md").read_text(), original)

    def test_gate_captures_any_current_body_without_manual_config(self):
        pass  # Gate capture is tested before the claim in GateTest.

    def test_issue_ten_needs_no_task_file(self):
        pass

    def test_rejects_stale_run_attempt_repository_issue_and_event(self):
        control.record_claim("1", str(self.out), str(self.record))
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

    def message_events(self, messages):
        path = self.directory / "messages.jsonl"
        path.write_text("\n".join(json.dumps({"type": kind, "part": {
            "messageID": message, **part}}) for message, kind, part in messages) + "\n")
        return str(path)

    def test_review_uses_final_message_after_progress_and_tools(self):
        filename = self.message_events([
            ("msg_progress", "step_start", {}),
            ("msg_progress", "text", {"text": "I will read the diff."}),
            ("msg_progress", "tool_use", {"tool": "read"}),
            ("msg_progress", "step_finish", {"reason": "tool-calls"}),
            ("msg_final", "step_start", {}),
            ("msg_final", "text", {"text": '{"findings":'}),
            ("msg_final", "text", {"text": '[{"blocking":true,"finding":"bug"}]}'}),
        ])
        self.assertEqual(control.review_axis(filename), [{"blocking": True, "finding": "bug"}])
        self.assertNotIn("I will read", control.review_markdown(filename))
        self.assertIn("I will read", control.reply(filename))

    def test_review_never_falls_back_to_earlier_valid_json(self):
        filename = self.message_events([
            ("msg_earlier", "text", {"text": '{"findings":[]}'}),
            ("msg_final", "step_start", {}),
            ("msg_final", "text", {"text": "Still working."}),
        ])
        self.assertRejects("invalid-review", filename)

    def test_review_rejects_mixed_or_reappearing_message_ids(self):
        for middle in (None, "", "msg_other"):
            with self.subTest(middle=middle):
                self.assertRejects("invalid-events", self.message_events([
                    ("msg_final", "text", {"text": '{"findings":'}),
                    (middle, "step_start", {}),
                    ("msg_final", "text", {"text": '[]}'}),
                ]))

    def test_review_does_not_discard_text_within_final_message(self):
        for before, after in (("Progress.", ""), ("", "Done.")):
            with self.subTest(before=before, after=after):
                self.assertRejects("invalid-review", self.message_events([
                    ("msg_final", "text", {"text": before + '{"findings":[]}' + after}),
                ]))

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

    def test_cli_writes_raw_replies_beside_review_output(self):
        # Pretty-printed, Unicode, split across text events: review.md keeps the replies verbatim.
        replies = {
            "Standards": '{\n  "findings": [\n    {"blocking": false,\n     "finding": "src/a.ts: 名前 🙂 '
                         + "y" * 70_000 + '"}\n  ]\n}\n\n',
            "Spec": '  {"findings": [{"blocking": true, "finding": "missing   spacing\\n\\tkept é"}]}',
        }
        files = [self.events(text[:31], text[31:], name=f"{axis}.jsonl") for axis, text in replies.items()]
        output = self.directory / "feedback/review.json"
        output.parent.mkdir()
        result = subprocess.run([sys.executable, "-I", str(CONTROL), "review", *files],
                                capture_output=True, text=True, env={**os.environ, "REVIEW_OUTPUT": str(output)})
        self.assertEqual((result.returncode, result.stdout), (0, "request_changes\n"), result.stderr)
        self.assertEqual(set(json.loads(output.read_text())), {"verdict", "findings", "advisory"})
        text = (output.parent / "review.md").read_text()
        standards, spec = text.index("Standards"), text.index("Spec")
        self.assertLess(standards, text.index(replies["Standards"]))
        self.assertLess(text.index(replies["Standards"]), spec)
        self.assertLess(spec, text.index(replies["Spec"]))
        for axis, reply in replies.items():
            with self.subTest(axis=axis):
                fence = text.rindex("```json\n", 0, text.index(reply))
                self.assertNotIn("```", text[fence + 8:text.index(reply)])
                self.assertIn("```", text[text.index(reply) + len(reply):])


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


class RetroTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.events = self.directory / "retro.jsonl"
        self.output = self.directory / "retro.md"

    def retro(self, *texts, extra=()):
        self.events.write_text("".join(json.dumps(event) + "\n" for event in (
            {"type": "step_start"}, *({"type": "text", "part": {"text": text}} for text in texts), *extra)))
        control.retro(str(self.events), str(self.output))
        return self.output.read_text()

    def test_writes_reply_text_with_exact_whitespace(self):
        self.assertEqual(self.retro("\n1. **Navigation**: ", "add a pointer.\n\n"),
                         "\n1. **Navigation**: add a pointer.\n\n")
        self.assertEqual(self.retro("  - 缩进\t", "kept 🙂"), "  - 缩进\tkept 🙂")

    def test_rejects_empty_or_failed_runs(self):
        for texts, extra, reason in (((), (), "invalid-retro"), (("  \n",), (), "invalid-retro"),
                                     (("ok",), ({"type": "error"},), "invalid-events")):
            with self.subTest(reason=reason, texts=texts), self.assertRaisesRegex(ValueError, f"^{reason}$"):
                self.retro(*texts, extra=extra)
        self.assertFalse(self.output.exists())

    def test_rejects_provider_truncated_replies(self):
        for reason in ("length", "content-filter"):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, "^incomplete-output$"):
                self.retro("1. Half a propo", extra=({"type": "step_finish", "part": {"reason": reason}},))
        self.assertFalse(self.output.exists())
        self.assertEqual(self.retro("Done.", extra=({"type": "step_finish", "part": {"reason": "stop"}},)),
                         "Done.")

    def test_has_no_length_limit(self):
        self.assertFalse(hasattr(control, "MAX_RETRO_CHARS"))
        text = "1. **提案** 🙂\n   " + "é" * 300_000 + "\n\n"
        self.assertEqual(self.retro(text[:7], text[7:]), text)


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

    def test_publishes_present_reports_in_round_order_then_retro(self):
        self.write("feedback-3/review.md", "### Spec — full response\n\n```json\n{\"findings\": []}\n```\n")
        self.write("feedback-1/review.md", "### Standards — full response\n\n```json\n{ \"a\":  1 }\n```\n")
        self.write("feedback-2/checks.json", '{"command": "pnpm test", "output": "boom"}')
        self.write("retro/retro.md", "\n  1. Keep  spacing.\n\n")
        documents = self.documents(self.comments())
        self.assertEqual([document["text"] for document in documents], [
            "### Standards — full response\n\n```json\n{ \"a\":  1 }\n```\n",
            "### Spec — full response\n\n```json\n{\"findings\": []}\n```\n",
            "\n  1. Keep  spacing.\n\n"])
        for document, label in zip(documents, ("round 1", "round 3", "retro")):
            with self.subTest(label=label):
                self.assertIn(label, document["preface"].lower())
        self.assertNotIn("pnpm test", "".join(document["text"] for document in documents))

    def test_neutralizes_mentions(self):
        self.write("retro/retro.md", "ping @maintainer and @org/team\n")
        [body] = self.comments()
        self.assertNotRegex(body.decode(), r"@(?!\u200b)")
        self.assertEqual(self.documents([body])[0]["text"], "ping @\u200bmaintainer and @\u200borg/team\n")

    def test_no_reports_write_no_comments(self):
        self.assertEqual(self.comments(), [])
        self.reports.mkdir()
        self.write("feedback-1/checks.json", "{}")
        self.assertEqual(self.comments(), [])

    def test_large_unicode_reports_split_within_limit_and_reassemble_exactly(self):
        review, retro = mixed_text(250_000), mixed_text(40_000)[::-1]
        self.write("feedback-2/review.md", review)
        self.write("retro/retro.md", retro)
        bodies = self.comments()
        self.assertEqual(control.COMMENT_BYTES, 60_000)
        # More than nine parts, so glob order has to keep numeric order.
        self.assertGreater(len(bodies), 10)
        for body in bodies:
            body.decode("utf-8")  # Never splits inside a character.
        documents = self.documents(bodies)
        self.assertEqual([document["text"] for document in documents],
                         [review.replace("@", "@\u200b"), retro.replace("@", "@\u200b")])
        self.assertGreater(documents[0]["total"], 1)
        self.assertGreater(documents[1]["total"], 1)

    def test_refuses_credentials_anywhere_in_large_reports(self):
        text = mixed_text(30_000)
        boundary = len(text.encode()[:59_000].decode(errors="ignore"))
        straddling = text[:boundary - 10] + f" {SECRET} " + text[boundary - 10:]
        for name, content, reason in (
            ("feedback-1/review.md", straddling, "credential-pattern-in-artifact"),
            ("feedback-4/review.md", text * 3 + " " + SECRET, "credential-pattern-in-artifact"),
            ("retro/retro.md", text * 3 + "opaque-credential-value", "credential-in-artifact"),
            ("retro/retro.md", "-----BEGIN PRIVATE KEY-----", "credential-pattern-in-artifact"),
        ):
            with self.subTest(name=name, reason=reason):
                shutil.rmtree(self.reports, ignore_errors=True)
                self.write(name, content)
                with self.assertRaisesRegex(ValueError, f"^{reason}$"):
                    self.comments()

    def test_cli_writes_comments_and_hides_credentials(self):
        self.write("feedback-1/review.md", "fine")
        args = [sys.executable, "-I", str(CONTROL), "comments", str(self.reports), str(self.output)]
        result = subprocess.run(args, capture_output=True, text=True, env={**os.environ})
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(self.documents([path.read_bytes() for path in sorted(self.output.glob("*.md"))])[0]["text"],
                         "fine")
        self.write("retro/retro.md", f"x {SECRET}")
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
    """Runs real supervised OpenCode step scripts against stub `opencode` binaries."""

    jobs = {"implement": ("software-factory-round.yml", "implement"),
            "review": ("software-factory-round.yml", "review"),
            "retro": ("software-factory-implement.yml", "retro"),
            "publish": ("software-factory-implement.yml", "retro-publish")}

    def run_step(self, job, opencode="exit 0", gh="exit 0", select="opencode run", env=None, files=None,
                 setup=None):
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
        # Every call is logged in order, NUL-separated, so tests can count sessions and calls.
        log = 'printf "%s\\0" "$@" > "$CALLS/$(printf %03d $(($(ls "$CALLS" | wc -l))))"\n'
        (bin_dir / "opencode").write_text(f"#!/bin/bash\n{log}{opencode}\n")
        (bin_dir / "gh").write_text(f"#!/bin/bash\n{log}{gh}\n")
        for stub in bin_dir.iterdir():
            stub.chmod(0o755)
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
        env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "MODEL": control.MODEL, "ISSUE": "6",
               "ROUND": "1", "RUNNER_TEMP": str(directory / "temp"), "FACTORY_AUTH_FILE": str(auth),
               "GITHUB_OUTPUT": str(directory / "output"), "GITHUB_STEP_SUMMARY": str(directory / "summary"),
               "GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": "123", "CALLS": str(directory / "calls"),
               "REVIEW_OUTPUT": str(directory / "temp/feedback/review.json"), **(env or {})}
        # Keep the real supervisor and cleanup; shorten only the workflow's model budget.
        script = re.sub(r' (600|1500) --', ' 1 --', step["run"])
        result = subprocess.run(["bash", "-e", "-c", script], cwd=cwd, env=env,
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
        for job in ("implement", "review", "retro"):
            with self.subTest(job=job):
                result, summary = self.run_step(job, self.stub_events(*leaky) + f"\necho {SECRET} >&2\nexec sleep 20")
                self.assertEqual(result.returncode, 124, result.stderr)
                self.assertIn('"exit_status": 124', result.stdout)
                self.assertIn('"tool_use": 4', summary)
                self.assertIn("::error::standards-timeout" if job == "review" else "::error::opencode-exit-124", result.stdout)
                self.assertNotIn(SECRET, result.stdout + result.stderr + summary)
                # A timed-out review stops before the second axis spends its budget.
                self.assertEqual(len(self.calls("opencode")), 1)

    def test_review_runner_error_stops_spec_and_retains_exit(self):
        result, _ = self.run_step("review", "exit 3")
        self.assertEqual(result.returncode, 3)
        self.assertEqual((self.directory / "output").read_text(), "standards=started\nstandards=runner-error\n")
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
        self.assertEqual((self.directory / "output").read_text(), "standards=started\nstandards=passed\nspec=started\nspec=passed\nverdict=approve\n")
        self.assertEqual(json.loads((self.directory / "temp/feedback/review.json").read_text())["advisory"],
                         ["Standards: src/a.ts: possible Mysterious Name", "Spec: src/a.ts: possible Mysterious Name"])
        raw = json.dumps({"findings": [{"blocking": False, "finding": "src/a.ts: possible Mysterious Name"}]})
        self.assertEqual((self.directory / "temp/feedback/review.md").read_text().count(raw), 2)

    def test_review_accepts_output_beyond_the_artifact_limit(self):
        finding = {"blocking": False, "finding": "src/a.ts: " + "说明 " * 100_000}
        reply = json.dumps({"findings": [finding]})
        result, _ = self.run_step("review", 'cat "$CALLS/../reply.jsonl"', files={
            "reply.jsonl": json.dumps({"type": "text", "part": {"text": reply}}) + "\n"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater((self.directory / "temp/feedback/review.json").stat().st_size, control.MAX_ARTIFACT_BYTES)
        self.assertEqual((self.directory / "temp/feedback/review.md").read_text().count(reply), 2)

    def test_review_rejects_old_schema(self):
        result, _ = self.run_step("review", self.reply({"verdict": "approve", "findings": []}))
        self.assertEqual(result.returncode, 1)
        self.assertIn("::error::invalid-review", result.stderr)
        self.assertEqual((self.directory / "output").read_text(), "standards=started\nstandards=invalid-output\n")

    def test_retro_writes_scanned_proposals(self):
        result, _ = self.run_step("retro", self.stub_events({"type": "text", "part": {"text": "Smooth run."}}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.directory / "temp/retro/retro.md").read_text(), "Smooth run.")
        result, _ = self.run_step("retro", self.stub_events({"type": "text", "part": {"text": f"see {SECRET}"}}))
        self.assertEqual(result.returncode, 1)
        self.assertIn("::error::credential-in-artifact", result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_retro_keeps_output_beyond_the_artifact_limit(self):
        text = "1. 提案 🙂\n" * 100_000
        result, _ = self.run_step("retro", 'cat "$CALLS/../reply.jsonl"', files={
            "reply.jsonl": json.dumps({"type": "text", "part": {"text": text}}) + "\n"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.directory / "temp/retro/retro.md").read_text(), text)

    def test_sessions_are_always_recorded_and_scanned(self):
        for job, events in (("implement", ["implementation"]), ("review", ["review-standards", "review-spec"]),
                            ("retro", ["retro"])):
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

    def publish(self, reports, pr=""):
        gh = (f'if [ "$1 $2" = "pr list" ]; then printf %s "{pr}"; fi\n'
              'if [ "$2" = comment ]; then mkdir -p "$CALLS/../bodies"\n'
              '  cp "$5" "$CALLS/../bodies/$(printf %03d $(ls "$CALLS" | wc -l))"; fi')
        # The publish job holds no model credential, so nothing points at an auth file.
        result, _ = self.run_step("publish", gh=gh, select="control.py comments", env={"FACTORY_AUTH_FILE": ""},
                                  files={f"temp/reports/{name}": content for name, content in reports.items()})
        bodies = self.directory / "bodies"
        return result, [path.read_bytes() for path in sorted(bodies.iterdir())] if bodies.exists() else []

    def test_retro_publish_comments_every_report_on_open_pr_else_issue(self):
        branch = "feat/6-implement"
        reports = {"feedback-1/review.md": "### Standards — full response\n\n```json\n{}\n```\n",
                   "feedback-2/checks.json": "{}",
                   "retro/retro.md": "1. **Navigation**: ping @maintainer about src/a.ts.\n"}
        for pr, target in (("17", ["pr", "comment", "17"]), ("", ["issue", "comment", "6"])):
            with self.subTest(pr=pr):
                result, bodies = self.publish(reports, pr)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = self.calls("gh")
                self.assertEqual([call[:2] for call in calls], [["pr", "list"], target[:2], target[:2]])
                self.assertIn(branch, calls[0])
                self.assertTrue(all(call[:3] == target for call in calls[1:]))
                review, retro = (body.decode() for body in bodies)
                self.assertIn("round 1", review.lower())
                self.assertIn("{}", review)
                self.assertIn("retro", retro.lower())
                self.assertIn("ping @\u200bmaintainer", retro)
                self.assertNotIn("ping @maintainer", retro)
                for body in (review, retro):
                    self.assertIn(f"https://github.com/{REPO}/actions/runs/123", body)

    def test_retro_publish_posts_whatever_reports_exist(self):
        for reports, count in (({"retro/retro.md": "Only retro."}, 1),
                               ({"feedback-1/review.md": "a", "feedback-3/review.md": "b"}, 2),
                               ({"feedback-1/checks.json": "{}"}, 0), ({}, 0)):
            with self.subTest(reports=list(reports)):
                result, bodies = self.publish(reports, "17")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(bodies), count)
                if not count:
                    self.assertEqual(self.calls("gh"), [])

    def test_retro_publish_splits_large_output_in_order(self):
        review = mixed_text(80_000)
        result, bodies = self.publish({"feedback-4/review.md": review, "retro/retro.md": "Done."}, "17")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(len(bodies), 2)
        self.assertTrue(all(len(body) <= 60_000 for body in bodies))
        chunks = [re.fullmatch(r"(.*?)Part (\d+)/(\d+)\n\n(.*)", body.decode(), re.DOTALL) for body in bodies]
        self.assertEqual([(int(match[2]), int(match[3])) for match in chunks],
                         [(n, len(bodies) - 1) for n in range(1, len(bodies))] + [(1, 1)])
        self.assertEqual("".join(match[4] for match in chunks[:-1]), review.replace("@", "@\u200b"))

    def test_retro_publish_refuses_credentials(self):
        for reports in ({"retro/retro.md": f"leak {SECRET}\n"},
                        {"feedback-1/review.md": "x" * 70_000 + " " + SECRET, "retro/retro.md": "fine"}):
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

    def test_issue_validation_steps_receive_model(self):
        validating = [step for step in self.steps()
                      if re.search(r"control\.py (gate-attempt|revalidate|record-claim|claimed) ", step.get("run", ""))]
        self.assertEqual(len(validating), 4)
        for step in validating:
            with self.subTest(step=step.get("name")):
                self.assertIn("MODEL", step.get("env", {}))

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
        self.assertIn("toJSON(needs)", str(jobs["report"]))

    def test_checked_patch_is_uploaded_before_candidate_code_runs(self):
        steps = self.round["jobs"]["verify"]["steps"]
        upload = next(index for index, step in enumerate(steps)
                      if step.get("with", {}).get("name") == "checked-${{ inputs.round }}")
        for index, step in enumerate(steps):
            if re.search(r"pnpm (lint|typecheck|build:admin|test)", step.get("run", "")):
                self.assertGreater(index, upload, step["run"])
        self.assertNotIn("secrets", str(self.round["jobs"]["verify"]))

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
            return {step["with"]["name"] for step in job["steps"]
                    if "download-artifact" in step.get("uses", "")}
        jobs = self.round["jobs"]
        self.assertEqual(downloads(jobs["review"]), {"factory-input", "checked-${{ inputs.round }}"})
        self.assertEqual(downloads(jobs["implement"]), {
            "factory-input", "checked-${{ steps.previous.outputs.round }}",
            "feedback-${{ steps.previous.outputs.round }}"})
        # Findings reach the PR as retro-publish comments, never through the PR body.
        handoff = self.implement["jobs"]["handoff"]
        self.assertEqual(downloads(handoff), {"checked-${{ steps.approved.outputs.round }}", "factory-claim", "factory-input"})
        self.assertNotIn("advisory", str(handoff))
        self.assertNotIn("review.json", str(handoff))

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

    def test_review_uploads_scanned_json_and_full_responses(self):
        steps = self.round["jobs"]["review"]["steps"]
        run = self.opencode_steps()["review"]["run"]
        for name in ('"$REVIEW_OUTPUT"', '"$RUNNER_TEMP/feedback/review.md"'):
            with self.subTest(name=name):
                self.assertIn(f"control.py scan-output {name}", run)
                self.assertLess(run.index("control.py review"), run.index(f"control.py scan-output {name}"))
        upload = next(step["with"] for step in steps
                      if step.get("with", {}).get("name") == "feedback-${{ inputs.round }}")
        self.assertEqual(upload["path"], "${{ runner.temp }}/feedback")

    def jobs(self):
        for workflow in (self.implement, self.round):
            yield from workflow["jobs"].items()

    def opencode_steps(self):
        return {name: step for name, job in self.jobs() for step in job.get("steps", [])
                if "opencode run" in step.get("run", "")}

    def test_model_deadlines(self):
        steps = self.opencode_steps()
        self.assertEqual(set(steps), {"implement", "review", "retro"})
        for name, seconds in (("implement", 1500), ("review", 600), ("retro", 600)):
            with self.subTest(job=name):
                self.assertEqual(re.findall(r' (\d+) -- \\\s+opencode run', steps[name]["run"]),
                                 [str(seconds)])

    def test_review_runs_both_axes_and_aggregates_both_files(self):
        run = self.opencode_steps()["review"]["run"]
        self.assertIn("for axis in standards spec; do", run)
        self.assertIn('prompt "review-$axis"', run)
        self.assertIn('"$RUNNER_TEMP/review-$axis.jsonl" "$RUNNER_TEMP/review-$axis-summary.txt" "review-$axis"', run)
        self.assertRegex(run, r'control\.py review \\\s+"\$RUNNER_TEMP/review-standards\.jsonl" '
                              r'"\$RUNNER_TEMP/review-spec\.jsonl"\)')

    def test_only_implementation_gets_shell(self):
        modes = {name: re.findall(r"control\.py configure \S+ (\w+)", step["run"])
                 for name, job in self.jobs() for step in job.get("steps", [])
                 if "control.py configure" in step.get("run", "")}
        self.assertEqual(modes, {"implement": ["implement"], "review": ["review"], "retro": ["retro"]})

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
        self.assertEqual(uploads, 3)

    def test_every_factory_artifact_expires_after_three_days(self):
        for name, job in self.jobs():
            for step in job.get("steps", []):
                if "upload-artifact" in step.get("uses", ""):
                    with self.subTest(job=name, artifact=step["with"]["name"]):
                        self.assertEqual(step["with"]["retention-days"], 3)

    def test_retro_reads_the_whole_run_without_write_access(self):
        retro = self.implement["jobs"]["retro"]
        self.assertEqual(retro["permissions"], {"contents": "read"})
        self.assertIn("always()", retro["if"])
        self.assertIn("needs.claim.result == 'success'", retro["if"])
        self.assertLessEqual({"claim", "round1", "round2", "round3", "round4", "handoff"}, set(retro["needs"]))
        downloads = [step["with"] for step in retro["steps"] if "download-artifact" in step.get("uses", "")]
        self.assertIn({"name": "factory-input", "path": "workspace/.factory-input"}, downloads)
        # One pattern per download, so a missing kind of artifact cannot hide the others.
        patterns = [item for item in downloads if "pattern" in item]
        self.assertEqual(sorted(item["pattern"] for item in patterns), ["checked-*", "feedback-*", "session-*"])
        for item in patterns:
            self.assertEqual(item["path"], "workspace/.factory-input/run")
            self.assertNotIn("merge-multiple", item)
        steps = [step for step in retro["steps"] if "download-artifact" in step.get("uses", "")
                 and "pattern" in step["with"]]
        self.assertTrue(all(step.get("continue-on-error") for step in steps))
        run = self.opencode_steps()["retro"]["run"]
        self.assertLess(run.index("control.py retro"), run.index("control.py scan-output "))

    def test_retro_publish_holds_no_model_secret_and_survives_failed_retro(self):
        publish = self.implement["jobs"]["retro-publish"]
        self.assertEqual(set(publish["needs"]), {"claim", "retro"})
        self.assertIn("always()", publish["if"])
        self.assertIn("needs.claim.result == 'success'", publish["if"])
        self.assertNotIn("needs.retro.result", publish["if"])
        self.assertNotIn("secrets", str(publish))
        self.assertNotIn("opencode", str(publish))
        self.assertEqual(publish["permissions"], {"contents": "read", "issues": "write", "pull-requests": "write"})
        downloads = [step for step in publish["steps"] if "download-artifact" in step.get("uses", "")]
        self.assertEqual([step["with"] for step in downloads], [
            {"pattern": "feedback-*", "path": "${{ runner.temp }}/reports"},
            {"name": "retro", "path": "${{ runner.temp }}/reports/retro"}])
        # A missing feedback or retro artifact must not stop the other reports from publishing.
        self.assertTrue(downloads[0].get("continue-on-error"))
        self.assertTrue(downloads[1].get("continue-on-error") or "needs.retro.result" in downloads[1].get("if", ""))
        run = next(step["run"] for step in publish["steps"] if "gh " in step.get("run", ""))
        self.assertIn('control.py comments "$RUNNER_TEMP/reports"', run)
        self.assertLess(run.index("control.py comments"), run.index("gh "))
        self.assertIn("--body-file", run)


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
        for mode in ("review", "retro"):
            with self.subTest(mode=mode):
                config = self.configure(mode)
                self.assertFalse(config["share"])
                self.assertEqual(config["permission"]["read"], {
                    "*": "allow", ".env": "deny", ".env.*": "deny", "**/.env": "deny",
                    "**/.env.*": "deny", ".env.example": "allow", "**/.env.example": "allow", "**/auth.json": "deny"})
                self.assertEqual(config["permission"]["*"], "deny")
                self.assertEqual(config["permission"]["edit"], "deny")
                for tool in self.denied:
                    self.assertEqual(config["permission"][tool], "deny")
                allowed = {tool for tool, rule in config["permission"].items() if rule == "allow"}
                self.assertEqual(allowed, {"glob", "grep", "list"})

    def test_implement_edits_unrestricted_paths_with_credentials_denied(self):
        permission = self.configure("implement")["permission"]
        self.assertEqual(permission["edit"], permission["read"])
        self.assertEqual(permission["edit"]["*"], "allow")
        self.assertEqual(permission["edit"][".env.example"], "allow")
        self.assertEqual(permission["edit"]["**/auth.json"], "deny")
        self.assertEqual(permission["bash"], "allow")

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
