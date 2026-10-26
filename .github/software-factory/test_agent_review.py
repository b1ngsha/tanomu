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

    def comment(self, part, total, digest="d" * 16, head=HEAD, user=BOT, prefix="", inline="none"):
        marker = f"<!-- tanomu-final-review head={head} digest={digest} part={part}/{total} inline={inline} -->"
        self.comments.append({"user": user, "body": f"{prefix}{marker}\nbody"})

    def test_writes_linked_issues_with_trusted_review_requirements(self):
        self.assertEqual(self.identify(), {"pr": "2", "head": HEAD, "base": BASE, "skip": "false",
                                           "spec": "true"})
        self.assertEqual(sorted(path.name for path in self.output.iterdir()),
                         ["identity.json", "issue-1.md", "issue-3.md"])
        self.assertEqual((self.output / "issue-1.md").read_text(), "# Issue #1: Thing\n\nDo it.\n")
        self.assertEqual((self.output / "issue-3.md").read_text(), "# Issue #3: Other\n\n\n")
        self.assertEqual(json.loads((self.output / "identity.json").read_text()),
                         {"pr": 2, "head": HEAD, "base": BASE, "issues": [1, 3], "run": "123",
                          "summary_format": "compact", "review_name": "Agent review"})

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

    def test_complete_summary_waits_for_its_inline_review(self):
        location = "e" * 16
        self.comment(1, 1, inline=location)
        self.assertEqual(self.identify()["skip"], "false")
        with mock.patch.object(control, "posted_inline", return_value={(HEAD, location)}):
            self.assertEqual(self.identify()["skip"], "true")
        with mock.patch.object(control, "posted_inline", return_value=set()):
            self.assertEqual(self.identify()["skip"], "false")

    def test_legacy_summary_is_recovered_before_assuming_completion(self):
        self.comments = [{"user": BOT, "body":
            f"<!-- tanomu-final-review head={HEAD} digest={'d' * 16} part=1/1 -->"}]
        self.assertEqual(self.identify()["skip"], "false")

    def test_final_head_records_bot_markers_only(self):
        self.comment(1, 2)
        self.comment(2, 2, user={"login": "github-actions[bot]", "type": "User"})
        self.identify(function=lambda number, _, directory: control.final_head(number, directory))
        self.assertEqual(json.loads(self.output.read_text()),
                         {"pr": 2, "head": HEAD, "eligible": True, "posted": [[HEAD, "d" * 16, 1, 2, "none"]]})
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
                    "advisory": ["Standards: smell"]})

    def write(self, result):
        (self.review / "review.json").write_text(json.dumps(result))

    def comments(self, posted=(), head=HEAD, eligible=True, reviews=None):
        current = {"pr": 2, "head": head, "eligible": eligible, "posted": list(posted)}
        for name, value in (("identity", self.identity), ("current", current)):
            (self.directory / f"{name}.json").write_text(json.dumps(value))
        fresh = control.final_comments(str(self.review), str(self.directory / "identity.json"),
                                       str(self.directory / "current.json"), str(self.output), reviews=reviews)
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
            parsed.append(([match[1], match[2], int(match[3]), int(match[4]), match[5]], preface, chunk))
        return parsed

    def test_publishes_the_structured_findings_once(self):
        [(marker, preface, chunk)] = self.parts(self.comments())
        self.assertEqual(chunk, "### Findings\n\n- **Blocking** — Spec: missing @​owner\n"
                                "- Advisory — Standards: smell\n")
        self.assertEqual(marker[1], hashlib.sha256((preface + chunk).encode()).hexdigest()[:16])
        self.assertIn("Spec: #1, #3.", preface)
        self.identity["issues"] = []
        self.write({"verdict": "approve", "findings": [], "advisory": []})
        [(_, preface, chunk)] = self.parts(self.comments())
        self.assertIn("only the Standards axis ran", preface)
        self.assertEqual(chunk, "### Findings\n\nNo findings.\n")

    def test_large_unicode_report_splits_losslessly_and_skips_posted_parts(self):
        finding = mixed_text(250_000)
        self.write({"verdict": "approve", "findings": [], "advisory": [finding]})
        parts = self.parts(self.comments())
        self.assertGreater(len(parts), 3)
        self.assertEqual([marker[2:4] for marker, _, _ in parts], [[i, len(parts)] for i in range(1, len(parts) + 1)])
        self.assertEqual("".join(chunk for _, _, chunk in parts),
                         "### Findings\n\n- Advisory — " + finding.replace("@", "@​") + "\n")
        missing = self.parts(self.comments([marker for marker, _, _ in parts if marker[2] not in (2, 3)]))
        self.assertEqual([marker[2] for marker, _, _ in missing], [2, 3])
        self.assertEqual(self.comments([marker for marker, _, _ in parts]), [])
        self.write({"verdict": "approve", "findings": [], "advisory": [finding + "x"]})
        self.assertEqual(len(self.parts(self.comments([marker for marker, _, _ in parts]))), len(parts))
        self.write({"verdict": "approve", "findings": [], "advisory": [finding]})
        self.identity["run"] = "124"
        self.assertEqual(len(self.comments([marker for marker, _, _ in parts])), len(parts))

    def test_posts_one_inline_review_and_dedupes_by_its_marker(self):
        self.write({"verdict": "request_changes", "findings": ["Standards: bug @owner"], "advisory": [],
                    "inline": [{"axis": "Standards", "blocking": True, "finding": "bug @owner",
                                "path": "src/a.ts", "line": 2}]})
        self.comments()
        payload = json.loads((self.output / "inline.json").read_text())
        self.assertEqual((payload["commit_id"], payload["event"]), (HEAD, "COMMENT"))
        self.assertEqual(payload["comments"], [{"path": "src/a.ts", "line": 2, "side": "RIGHT",
                                                "body": "**Standards · blocking** — bug @​owner"}])
        marker = control.INLINE_MARKER.fullmatch(payload["body"].split("\n", 1)[0])
        self.assertEqual(marker[1], HEAD)
        (self.output / "inline.json").unlink()
        for user, expected in ((BOT, False), ({"login": "mallory", "type": "User"}, True)):
            with self.subTest(user=user["login"]):
                self.comments(reviews=[[{"body": payload["body"], "user": user}]])
                self.assertEqual((self.output / "inline.json").exists(), expected)
                (self.output / "inline.json").unlink(missing_ok=True)
        self.write({"verdict": "approve", "findings": [], "advisory": [], "inline": []})
        self.comments()
        self.assertFalse((self.output / "inline.json").exists())

    def test_stale_head_posts_nothing(self):
        self.assertIsNone(self.comments(eligible=False))
        self.assertIsNone(self.comments(head=OTHER))
        self.assertFalse(self.output.exists())

    def test_refuses_credentials_in_summary_or_inline_comments(self):
        for result in ({"verdict": "approve", "findings": [f"x {SECRET}"], "advisory": []},
                       {"verdict": "approve", "findings": [], "advisory": [],
                        "inline": [{"axis": "Standards", "blocking": False, "finding": SECRET,
                                    "path": "src/a.ts", "line": 2}]}):
            with self.subTest(inline="inline" in result):
                self.write(result)
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


class InlineFindingsTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.patch = self.directory / "final.patch"
        self.patch.write_text("""diff --git a/src/a.ts b/src/a.ts
--- a/src/a.ts
+++ b/src/a.ts
@@ -1,2 +1,3 @@
 context
-old
+new one
+new two
 tail
""")

    def review(self, findings):
        result = self.directory / "result.json"
        result.write_text(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                                      "structured_output": {"findings": findings}}))
        output = self.directory / "review.json"
        with mock.patch.dict(os.environ, {"FINAL_PATCH": str(self.patch)}):
            return control.claude_review_result([("Standards", str(result))], str(output))

    def test_keeps_only_locations_that_exist_in_the_diff(self):
        report = self.review([
            {"blocking": True, "finding": "bug", "path": "src/a.ts", "line": 2},
            {"blocking": False, "finding": "added", "path": "src/a.ts", "line": 3},
            {"blocking": False, "finding": "outside", "path": "src/a.ts", "line": 9},
            {"blocking": False, "finding": "wrong file", "path": "src/b.ts", "line": 1},
            {"blocking": False, "finding": "unlocated"},
            {"blocking": False, "finding": "null", "path": None, "line": None},
        ])
        self.assertEqual(report["inline"], [
            {"axis": "Standards", "blocking": True, "finding": "bug", "path": "src/a.ts", "line": 2},
            {"axis": "Standards", "blocking": False, "finding": "added", "path": "src/a.ts", "line": 3}])
        self.assertEqual(json.loads((self.directory / "review.json").read_text())["inline"], report["inline"])

    def test_rejects_malformed_locations(self):
        for item in ({"path": 1}, {"line": 0}, {"line": "2"}, {"path": " "}):
            with self.subTest(item=item):
                with self.assertRaisesRegex(ValueError, "^invalid-findings$"):
                    control.validate_findings({"findings": [{"blocking": False, "finding": "x", **item}]})


class ClaudeResultTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def write(self, event):
        path = self.directory / "result.json"
        path.write_text(json.dumps(event))
        return str(path)

    def test_reads_native_structured_results(self):
        filename = self.write({"type": "result", "subtype": "success", "is_error": False,
                               "structured_output": {"findings": [{"blocking": True, "finding": "bug"}]},
                               "result": "Done."})
        self.assertEqual(control.claude_findings(filename), [{"blocking": True, "finding": "bug"}])

    def test_rejects_incomplete_or_unstructured_results(self):
        base = {"type": "result", "subtype": "success", "is_error": False}
        for event, reason in ((base, "no-structured-output"), ({"type": "assistant"}, "no-result")):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, f"^{reason}$"):
                control.claude_findings(self.write(event))
        (self.directory / "empty.json").write_text("")
        with self.assertRaisesRegex(ValueError, "^invalid-claude-result$"):
            control.claude_result(self.directory / "empty.json")

    def test_rejects_provider_failure_and_structured_output_exhaustion(self):
        for subtype, reason in (("error_max_structured_output_retries", "structured-output-retries"),
                                ("error_max_turns", "max-turns"), ("error_api", "provider-error")):
            with self.subTest(subtype=subtype), self.assertRaisesRegex(ValueError, f"^{reason}$"):
                control.claude_result(self.write({"type": "result", "subtype": subtype, "is_error": True}))

    def test_rejects_duplicate_keys_and_invalid_findings(self):
        path = self.directory / "duplicate.json"
        path.write_text('{"type":"result","subtype":"success","structured_output":{"findings":[],"findings":[]}}')
        with self.assertRaisesRegex(ValueError, "^invalid-claude-result$"):
            control.claude_result(path)
        with self.assertRaisesRegex(ValueError, "^invalid-findings$"):
            control.claude_findings(self.write({"type": "result", "subtype": "success", "is_error": False,
                "structured_output": {"findings": [{"blocking": "yes", "finding": "x"}]}}))

    def test_copies_only_a_named_native_transcript(self):
        session = "123e4567-e89b-42d3-a456-426614174000"
        source = self.directory / "config/projects/factory" / f"{session}.jsonl"
        source.parent.mkdir(parents=True)
        source.write_text('{"native":true}\n')
        output = self.directory / "evidence.jsonl"
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.directory / "config")}):
            control.claude_transcript(session, output)
            self.assertEqual(output.read_text(), source.read_text())
            with self.assertRaisesRegex(ValueError, "^invalid-session-id$"):
                control.claude_transcript("../auth", output)
            source.unlink()
            with self.assertRaisesRegex(ValueError, "^missing-transcript$"):
                control.claude_transcript(session, output)


class ClaudeConfigureTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.github_env = self.directory / "github-env"
        self.enterContext(mock.patch.dict(os.environ, {
            "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
            "ANTHROPIC_MODEL": "deepseek-flash",
            "ANTHROPIC_API_KEY": SECRET,
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
        self.assertTrue(settings["permissions"]["blockReadsOutsideWorkingDirectories"])
        self.assertEqual(settings["permissions"]["disableBypassPermissionsMode"], "disable")
        self.assertEqual(settings["permissions"]["allow"], ["Read", "Glob", "Grep"])
        self.assertTrue(any("Read(//" in item for item in settings["permissions"]["deny"]))

    def test_rejects_unknown_or_unsafe_provider_endpoints(self):
        for base_url, reason in (("http://api.deepseek.com/anthropic", "invalid-provider"),
                                 ("https://example.test/anthropic", "invalid-provider"),
                                 ("https://api.deepseek.com/anthropic?key=leak", "invalid-provider")):
            with self.subTest(base_url=base_url), mock.patch.dict(os.environ,
                    {"ANTHROPIC_BASE_URL": base_url}):
                with self.assertRaisesRegex(ValueError, f"^{reason}$"):
                    control.configure_claude(str(self.directory / "claude"))


class OptionalSpecTest(unittest.TestCase):
    def test_review_without_spec_axis(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        result = directory / "standards.json"
        result.write_text(json.dumps({"type": "result", "subtype": "success", "is_error": False,
            "structured_output": {"findings": [{"blocking": True, "finding": "x"}]}}))
        output = directory / "review.json"
        completed = subprocess.run([sys.executable, "-I", str(CONTROL), "claude-result",
                                    f"Standards={result}", str(output)], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(output.read_text()),
                         {"verdict": "request_changes", "findings": ["Standards: x"], "advisory": []})
        self.assertFalse((directory / "review.md").exists())


if __name__ == "__main__":
    unittest.main()
