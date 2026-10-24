import contextlib
import copy
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
import test_control as base  # noqa: E402
from test_control import CONTROL, REPO, SECRET, TaskDirectory, mixed_text  # noqa: E402

HEAD, BASE, OTHER = "a" * 40, "b" * 40, "c" * 40
BOT = {"login": "github-actions[bot]", "type": "Bot"}


class FinalPromptTest(TaskDirectory):
    def setUp(self):
        super().setUp()
        for name in ("prompts", "skills"):
            shutil.copytree(CONTROL.parent / name, self.root / name)

    def test_final_prompts_name_the_pr_diff(self):
        axes = control.review_axes()
        for axis in ("standards", "spec"):
            with self.subTest(axis=axis):
                text = control.prompt(f"final-{axis}", BASE, HEAD)
                for expected in (BASE, HEAD, ".factory-input/final.patch", ".factory-input/issue-*.md",
                                 "AGENTS.md", f"You are the {axis.title()} sub-agent", axes[axis]["brief"]):
                    self.assertIn(expected, text)
                for absent in ("no commit", "candidate.patch", "task.json", "Check the thing.", "task-*.md",
                               "AXIS", "BLOCKING", "DIFF", "ACCEPTANCE"):
                    self.assertNotIn(absent, text)

    def test_final_prompts_reject_malformed_revisions(self):
        for args in ((BASE, "HEAD"), (BASE, HEAD[:-1]), (BASE.upper(), HEAD)):
            with self.subTest(args=args):
                self.assertRejects("invalid-sha", control.prompt, "final-spec", *args)


class FinalIdentifyTest(TaskDirectory):
    def setUp(self):
        super().setUp()
        self.output = self.root / "final-input"
        self.enterContext(mock.patch.dict(os.environ, {"GITHUB_REF": "refs/heads/main",
                                                       "GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": "123"}))
        self.pull = {"state": "open", "user": {"type": "User"}, "head": {"sha": HEAD, "repo": {"full_name": REPO}},
                     "base": {"ref": "main", "sha": OTHER, "repo": {"full_name": REPO}},
                     "body": "Closes #1\nfixes: #3, RESOLVED #1, refs #4\nCloses other/repo#5 and "
                             "https://github.com/x/y/issues/6\nprefixes #7"}
        url = f"https://api.github.com/repos/{REPO}"
        self.issues = {1: {"title": "Thing", "body": "Do it.", "repository_url": url},
                       3: {"title": "Other", "body": None, "repository_url": url},
                       4: {"title": "A PR", "pull_request": {}, "repository_url": url}}
        self.comments = []

    def api(self, path):
        if path == f"repos/{REPO}/pulls/2":
            return self.pull
        if path == f"repos/{REPO}/compare/{OTHER}...{HEAD}":
            return {"merge_base_commit": {"sha": BASE}}
        return self.issues[int(path.removeprefix(f"repos/{REPO}/issues/"))]

    def identify(self, event="pull_request_target", function=control.final_identify):
        pages = json.dumps([self.comments[:1], self.comments[1:]]).encode()
        with mock.patch.object(control, "api", self.api), \
                mock.patch.object(control.subprocess, "check_output", return_value=pages):
            return function("2", event, str(self.output))

    def comment(self, part, total, digest="d" * 16, head=HEAD, user=BOT, prefix=""):
        marker = f"<!-- tanomu-final-review head={head} digest={digest} part={part}/{total} -->"
        self.comments.append({"user": user, "body": f"{prefix}{marker}\nbody"})

    def test_writes_linked_issues_with_trusted_review_requirements(self):
        self.assertEqual(self.identify(), {"pr": "2", "head": HEAD, "base": BASE, "skip": "false",
                                           "spec": "true"})
        self.assertEqual(sorted(path.name for path in self.output.iterdir()),
                         ["identity.json", "issue-1.md", "issue-3.md"])
        self.assertEqual((self.output / "issue-1.md").read_text(), "# Issue #1: Thing\n\nDo it.\n")
        self.assertEqual((self.output / "issue-3.md").read_text(), "# Issue #3: Other\n\n\n")
        self.assertEqual(json.loads((self.output / "identity.json").read_text()),
                         {"pr": 2, "head": HEAD, "base": BASE, "issues": [1, 3], "run": "123"})

    def test_no_linked_issue_runs_standards_only(self):
        self.pull["body"] = None
        self.assertEqual(self.identify()["spec"], "false")
        self.assertEqual(json.loads((self.output / "identity.json").read_text())["issues"], [])

    def test_rejects_unreviewable_pull_requests(self):
        for change, reason in (
            (lambda: self.pull.update(state="closed"), "not-open-pr"),
            (lambda: self.pull["head"].update(repo={"full_name": "fork/tanomu"}), "fork-pr"),
            (lambda: self.pull["head"].update(repo=None), "fork-pr"),
            (lambda: self.pull["base"].update(ref="next"), "wrong-base"),
            (lambda: self.pull["head"].update(sha="a" * 39), "invalid-sha"),
            (lambda: os.environ.update(GITHUB_REF="refs/heads/next"), "wrong-ref"),
            (lambda: self.issues[3].update(repository_url="https://api.github.com/repos/x/y"), "foreign-issue"),
        ):
            with self.subTest(reason=reason), mock.patch.dict(os.environ), \
                    mock.patch.object(self, "pull", copy.deepcopy(self.pull)), \
                    mock.patch.object(self, "issues", copy.deepcopy(self.issues)):
                change()
                self.assertRejects(reason, self.identify)
        self.assertRejects("invalid-event", self.identify, "push")

    def test_automatic_entry_skips_bots_and_complete_sets(self):
        self.pull["user"]["type"] = "Bot"
        self.assertEqual(self.identify()["skip"], "true")
        # Bot PRs never get their issue references fetched.
        self.assertEqual([path.name for path in self.output.iterdir()], ["identity.json"])
        self.assertEqual(self.identify("workflow_dispatch")["skip"], "false")
        self.pull["user"]["type"] = "User"
        self.comment(2, 2)
        self.comment(1, 2, user={"login": "mallory", "type": "User"})
        self.comment(1, 2, prefix="quoted ")
        self.comment(1, 3, digest="e" * 16)
        self.comment(1, 1, head=OTHER)
        self.assertEqual(self.identify()["skip"], "false")
        self.comment(1, 2)
        self.assertEqual(self.identify()["skip"], "true")
        self.assertEqual(self.identify("workflow_dispatch")["skip"], "false")

    def test_final_head_records_bot_markers_only(self):
        self.comment(1, 2)
        self.comment(2, 2, user={"login": "github-actions[bot]", "type": "User"})
        self.identify(function=lambda number, _, directory: control.final_head(number, directory))
        self.assertEqual(json.loads(self.output.read_text()),
                         {"pr": 2, "head": HEAD, "eligible": True, "posted": [[HEAD, "d" * 16, 1, 2]]})
        # A PR closed or retargeted after its review is recorded, not rejected.
        self.pull.update(state="closed")
        self.pull["base"]["ref"] = "next"
        self.identify(function=lambda number, _, directory: control.final_head(number, directory))
        self.assertFalse(json.loads(self.output.read_text())["eligible"])


class PrDiffTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(contextlib.chdir(self.directory))
        self.git("init", "-q", "-b", "main")
        self.base = self.commit("a.txt", "base\n")
        self.git("checkout", "-q", "-b", "pr")
        Path("image.bin").write_bytes(b"\0\1\2")
        self.head = self.commit("a.txt", "pr change\n")
        self.git("checkout", "-q", "main")
        self.commit("later.txt", "later main\n")
        self.git("checkout", "-q", "pr")

    def git(self, *args):
        return subprocess.check_output(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args]).decode().strip()

    def commit(self, name, content=None):
        if content is not None:
            Path(name).write_text(content)
        self.git("add", "--all")
        self.git("commit", "-q", "-m", name)
        return self.git("rev-parse", "HEAD")

    def assertRejects(self, reason, *args):
        with self.assertRaises(ValueError) as caught:
            control.pr_diff(*(args or (self.head, self.base)))
        self.assertEqual(str(caught.exception), reason)

    def test_writes_binary_diff_from_merge_base(self):
        control.pr_diff(self.head, self.base)
        patch = Path(".factory-input/final.patch").read_bytes()
        self.assertIn(b"+pr change", patch)
        self.assertIn(b"GIT binary patch", patch)
        self.assertNotIn(b"later", patch)
        self.git("checkout", "-q", "-B", "check", self.base)
        subprocess.run(["git", "apply", "--check", "--binary", ".factory-input/final.patch"], check=True)

    def test_rejects_unpinned_or_dirty_checkouts(self):
        self.assertRejects("invalid-sha", self.head[:12], self.base)
        self.assertRejects("head-mismatch", self.base, self.base)
        self.assertRejects("invalid-base", self.head, self.git("rev-parse", "main"))
        Path("a.txt").write_text("dirty\n")
        self.assertRejects("dirty-worktree")
        self.git("checkout", "-q", "a.txt")
        Path("untracked").write_text("x")
        self.assertRejects("dirty-worktree")

    def test_rejects_tracked_factory_input_before_writing(self):
        outside = self.directory.parent / f"{self.directory.name}-outside"
        for make in (lambda: Path(".factory-input").mkdir() or Path(".factory-input/issue-1.md").write_text("x"),
                     lambda: Path(".factory-input").symlink_to(outside)):
            with self.subTest():
                self.git("checkout", "-q", "-B", "planted", self.head)
                make()
                head = self.commit(".factory-input")
                self.assertRejects("factory-input-exists", head, self.base)
                self.assertFalse(outside.exists())


class FinalCommentsTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.review = self.directory / "final-review"
        self.review.mkdir()
        self.output = self.directory / "comments"
        self.enterContext(mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": "123"}))
        os.environ.pop("FACTORY_AUTH_FILE", None)
        self.identity = {"pr": 2, "head": HEAD, "base": BASE, "issues": [1, 3], "run": "123"}
        self.write({"verdict": "request_changes", "findings": ["Spec: missing @owner"],
                    "advisory": ["Standards: smell"]}, "### Spec — full response\n\nraw @team reply\n")

    def write(self, result, markdown):
        (self.review / "review.json").write_text(json.dumps(result))
        (self.review / "review.md").write_text(markdown)

    def comments(self, posted=(), head=HEAD, eligible=True):
        current = {"pr": 2, "head": head, "eligible": eligible, "posted": list(posted)}
        for name, value in (("identity", self.identity), ("current", current)):
            (self.directory / f"{name}.json").write_text(json.dumps(value))
        fresh = control.final_comments(str(self.review), str(self.directory / "identity.json"),
                                       str(self.directory / "current.json"), str(self.output))
        bodies = [path.read_bytes().decode() for path in sorted(self.output.glob("*.md"))] if fresh else None
        for path in self.output.glob("*.md"):
            path.unlink()
        return bodies

    def parts(self, bodies):
        parsed = []
        for body in bodies:
            self.assertLessEqual(len(body.encode()), control.COMMENT_BYTES)
            marker, rest = body.split("\n", 1)
            match = control.FINAL_MARKER.fullmatch(marker)
            self.assertEqual(match[1], HEAD)
            preface, counter, chunk = re.fullmatch(r"(.*?)(Part \d+/\d+)\n\n(.*)", rest, re.DOTALL).groups()
            self.assertEqual(counter, f"Part {match[3]}/{match[4]}")
            self.assertIn(f"{REPO}/actions/runs/123", preface)
            parsed.append(([match[1], match[2], int(match[3]), int(match[4])], preface, chunk))
        return parsed

    def test_publishes_findings_summary_then_verbatim_response(self):
        [(marker, preface, chunk)] = self.parts(self.comments())
        self.assertEqual(chunk, "### Findings\n\n- **Blocking** — Spec: missing @​owner\n"
                                "- Advisory — Standards: smell\n\n### Spec — full response\n\nraw @​team reply\n")
        self.assertEqual(marker[1], hashlib.sha256((preface + chunk).encode()).hexdigest()[:16])
        self.assertIn("Spec: #1, #3.", preface)
        self.identity["issues"] = []
        self.write({"verdict": "approve", "findings": [], "advisory": []}, "")
        [(_, preface, chunk)] = self.parts(self.comments())
        self.assertIn("only the Standards axis ran", preface)
        self.assertEqual(chunk, "### Findings\n\nNo findings.\n\n")

    def test_large_unicode_report_splits_losslessly_and_skips_posted_parts(self):
        markdown = mixed_text(250_000)
        self.write({"verdict": "approve", "findings": [], "advisory": []}, markdown)
        parts = self.parts(self.comments())
        self.assertGreater(len(parts), 3)
        self.assertEqual([marker[2:] for marker, _, _ in parts], [[i, len(parts)] for i in range(1, len(parts) + 1)])
        self.assertEqual("".join(chunk for _, _, chunk in parts),
                         "### Findings\n\nNo findings.\n\n" + markdown.replace("@", "@​"))
        # A rerun with the same report fills in only the missing parts, in order.
        missing = self.parts(self.comments([marker for marker, _, _ in parts if marker[2] not in (2, 3)]))
        self.assertEqual([marker[2] for marker, _, _ in missing], [2, 3])
        self.assertEqual(self.comments([marker for marker, _, _ in parts]), [])
        # A different report gets a new digest, so the whole set is posted again.
        self.write({"verdict": "approve", "findings": [], "advisory": []}, markdown + "x")
        self.assertEqual(len(self.parts(self.comments([marker for marker, _, _ in parts]))), len(parts))
        # So does an identical report from a new run, such as a manual re-review.
        self.write({"verdict": "approve", "findings": [], "advisory": []}, markdown)
        self.identity["run"] = "124"
        self.assertEqual(len(self.comments([marker for marker, _, _ in parts])), len(parts))

    def test_stale_head_posts_nothing(self):
        self.assertIsNone(self.comments(eligible=False))
        self.assertIsNone(self.comments(head=OTHER))
        self.assertFalse(self.output.exists())

    def test_refuses_credentials_in_either_file(self):
        for result, markdown in (({"verdict": "approve", "findings": [f"x {SECRET}"], "advisory": []}, ""),
                                 ({"verdict": "approve", "findings": [], "advisory": []}, mixed_text(90_000) + SECRET)):
            with self.subTest(markdown=len(markdown)):
                self.write(result, markdown)
                self.assertRaisesRegex(ValueError, "^credential-pattern-in-artifact$", self.comments)

    def test_cli_reports_stale_head_and_writes_comments(self):
        self.comments()
        args = [sys.executable, "-I", str(CONTROL), "final-comments", str(self.review),
                str(self.directory / "identity.json"), str(self.directory / "current.json"), str(self.output)]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(len(list(self.output.glob("*.md"))), 1)
        self.comments(head=OTHER)
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout), (0, "::notice::final-review-stale\n"))


class ClaudeResultTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def write(self, events):
        path = self.directory / "events.jsonl"
        path.write_text("\n".join(json.dumps(event) for event in events) + "\n")
        return str(path)

    def assertReason(self, events, reason):
        with self.assertRaisesRegex(ValueError, f"^{reason}$"):
            control.claude_result(self.write(events))

    def test_accepts_successful_structured_output(self):
        output, findings = control.claude_result(self.write([
            {"type": "system", "subtype": "init"},
            {"type": "result", "subtype": "success", "is_error": False,
             "structured_output": {"findings": [{"blocking": True, "finding": "bug"}]}},
        ]))
        self.assertEqual(output["findings"], findings)

    def test_rejects_incomplete_or_unstructured_results(self):
        base = {"type": "result", "subtype": "success", "is_error": False}
        for event, reason in ((base, "no-structured-output"),
                              ({**base, "structured_output": {"findings": []}}, "no-result")):
            with self.subTest(reason=reason):
                events = [event] if reason == "no-result" else [{"type": "system"}, event]
                if reason == "no-result":
                    events.append({"type": "assistant"})
                self.assertReason(events, reason)

    def test_rejects_provider_failure_and_structured_output_exhaustion(self):
        for subtype, reason in (("error_max_structured_output_retries", "structured-output-retries"),
                                ("error_max_turns", "max-turns"), ("error_api", "provider-error")):
            with self.subTest(subtype=subtype):
                self.assertReason([{"type": "result", "subtype": subtype, "is_error": True}], reason)

    def test_rejects_duplicate_keys_and_invalid_findings(self):
        path = self.directory / "duplicate.jsonl"
        path.write_text('{"type":"result","subtype":"success","structured_output":{"findings":[],"findings":[]}}\n')
        with self.assertRaisesRegex(ValueError, "^invalid-claude-events$"):
            control.claude_result(str(path))
        self.assertReason([{"type": "result", "subtype": "success",
                            "structured_output": {"findings": [{"blocking": "yes", "finding": "x"}]}}],
                          "invalid-findings")

    def test_writes_unavailable_report_without_model_text(self):
        failed = self.write([{"type": "result", "subtype": "error_max_structured_output_retries"}])
        output = self.directory / "review.json"
        report = control.claude_review_result([("Standards", failed, "0")], str(output))
        self.assertEqual(report, {"verdict": "unavailable", "findings": [], "advisory": [],
                                  "unavailable": [{"axis": "Standards", "reason": "structured-output-retries"}]})
        self.assertNotIn("error_max", (output.with_suffix(".md")).read_text())


class ClaudeConfigureTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.github_env = self.directory / "github-env"
        self.enterContext(mock.patch.dict(os.environ, {
            "FACTORY_REVIEW_BASE_URL": "https://api.deepseek.com/anthropic",
            "FACTORY_REVIEW_MODEL": "deepseek-flash",
            "FACTORY_REVIEW_API_KEY": SECRET,
            "GITHUB_ENV": str(self.github_env),
        }))

    def test_writes_isolated_settings_and_only_paths_to_github_env(self):
        control.configure_claude(str(self.directory / "claude"))
        lines = self.github_env.read_text().splitlines()
        self.assertIn("FACTORY_AUTH_FILE=", "\n".join(lines))
        self.assertNotIn(SECRET, self.github_env.read_text())
        auth = self.directory / "claude/auth.json"
        self.assertEqual(auth.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(auth.read_text()), {"key": SECRET})
        settings = json.loads((self.directory / "claude/config/settings.json").read_text())
        self.assertTrue(settings["blockReadsOutsideWorkingDirectories"])
        self.assertEqual(settings["permissions"]["allow"], ["Read", "Glob", "Grep"])
        self.assertTrue(any("Read(//" in item for item in settings["permissions"]["deny"]))

    def test_rejects_unknown_or_unsafe_provider_endpoints(self):
        for base_url, reason in (("http://api.deepseek.com/anthropic", "invalid-provider"),
                                 ("https://example.test/anthropic", "invalid-provider"),
                                 ("https://api.deepseek.com/anthropic?key=leak", "invalid-provider")):
            with self.subTest(base_url=base_url), mock.patch.dict(os.environ,
                    {"FACTORY_REVIEW_BASE_URL": base_url}):
                with self.assertRaisesRegex(ValueError, f"^{reason}$"):
                    control.configure_claude(str(self.directory / "claude"))


class SpikeWorkflowContractTest(unittest.TestCase):
    def setUp(self):
        self.workflow = base.WorkflowContractTest.load("final-review-claude-spike.yml")
        self.jobs = self.workflow["jobs"]

    def test_is_manual_only_and_has_no_publisher(self):
        triggers = self.workflow[True]
        self.assertEqual(set(triggers), {"workflow_dispatch"})
        self.assertEqual(set(self.jobs), {"identify", "review"})
        self.assertEqual(self.workflow["permissions"], {})
        self.assertIn("github.ref == 'refs/heads/main'", self.jobs["identify"]["if"])

    def test_model_job_has_read_only_boundary_and_secret_is_scoped(self):
        self.assertEqual(self.jobs["review"]["permissions"], {"contents": "read"})
        text = json.dumps(self.jobs)
        self.assertIn("FACTORY_REVIEW_API_KEY", text)
        self.assertNotIn("GH_TOKEN", json.dumps(self.jobs["review"]))
        self.assertNotIn("gh pr comment", text)
        self.assertIn("--bare", text)
        self.assertIn("--restricted", text)
        self.assertIn("--strict-mcp-config", text)
        self.assertIn("--tools Read,Glob,Grep", text)
        self.assertNotIn("--dangerously-skip-permissions", text)
        self.assertNotIn("bypassPermissions", text)

    def test_identify_writes_the_uploaded_input(self):
        identify, upload = self.jobs["identify"]["steps"][1:3]
        self.assertIn('final-identify "$PR" workflow_dispatch "$RUNNER_TEMP/final-input"', identify["run"])
        self.assertEqual(upload["with"]["path"], "${{ runner.temp }}/final-input")

    def test_trusted_scripts_resolve_from_each_working_directory(self):
        prefixes = {("identify", None): {""}, ("review", None): {"trusted/"},
                    ("review", "candidate"): {"../trusted/", '"$GITHUB_WORKSPACE/trusted/'}}
        for name, job in self.jobs.items():
            for step in job["steps"]:
                for prefix in re.findall(r'(\S*)\.github/software-factory/', step.get("run", "")):
                    with self.subTest(job=name, step=step.get("name"), prefix=prefix):
                        self.assertIn(prefix, prefixes[(name, step.get("working-directory"))])

    def test_runner_and_artifacts_are_pinned(self):
        text = json.dumps(self.jobs["review"])
        self.assertIn("@anthropic-ai/claude-code@2.1.304", text)
        self.assertIn("2.1.304 (Claude Code)", text)
        uploads = [step for step in self.jobs["review"]["steps"] if "upload-artifact" in step.get("uses", "")]
        self.assertTrue(uploads)
        self.assertTrue(all(step["with"]["retention-days"] == 3 for step in uploads))
        self.assertTrue(all("*" not in step["with"]["path"] for step in uploads))


class OptionalSpecTest(unittest.TestCase):
    def test_review_without_spec_axis(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        events = directory / "standards.jsonl"
        events.write_text(json.dumps({"type": "text", "part": {"text": '{"findings":[{"blocking":true,'
                                                                       '"finding":"x"}]}'}}) + "\n")
        output = directory / "review.json"
        result = subprocess.run([sys.executable, "-I", str(CONTROL), "review", str(events)],
                                capture_output=True, text=True, env={**os.environ, "REVIEW_OUTPUT": str(output)})
        self.assertEqual((result.returncode, result.stdout), (0, "request_changes\n"), result.stderr)
        self.assertEqual(json.loads(output.read_text())["findings"], ["Standards: x"])
        self.assertNotIn("Spec", (directory / "review.md").read_text())


if __name__ == "__main__":
    unittest.main()
