import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("publication", Path(__file__).with_name("publication.py"))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PublicationTest(unittest.TestCase):
    def test_pr_body_uses_only_trusted_facts_in_the_pinned_template(self):
        template = (Path(__file__).with_name("skills") / "pr/SKILL.md").read_text()
        body = p.pr_body("17", "3", "owner/tanomu", "123", template)
        self.assertLess(body.index("## Summary"), body.index("## Evidence"))
        self.assertLess(body.index("## Evidence"), body.index("## Merge Danger"))
        self.assertIn("Issue #17\n  -> checked patch (round 3)", body)
        self.assertIn("Refs #17.", body)
        self.assertIn("**Door:** requires human assessment", body)
        self.assertIn("**Blast Radius:** unassessed", body)
        self.assertIn("format, lint, typecheck, admin build, database tests", body)
        self.assertIn("Acceptance has not been performed.", body)
        self.assertTrue(body.endswith("🤖 Generated with [Claude Code](https://claude.com/claude-code)\n"))
        for invalid in ("## Summary", template.replace("<one-way or two-way>", "<unexpected>")):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "invalid-pr-template"):
                    p.pr_body("17", "2", "owner/tanomu", "123", invalid)

    def test_compact_summary_keeps_only_findings_without_inline_delivery(self):
        identity = {"run": "1", "head": "a" * 40, "base": "b" * 40, "issues": [],
                    "summary_format": "compact"}
        large = "x" * 60_001
        result = {"findings": ["Standards: inline bug", "Spec: general requirement"],
                  "advisory": ["Standards: " + large], "inline": [
                      {"axis": "Standards", "blocking": True, "finding": "inline bug",
                       "path": "src/a.ts", "line": 1},
                      {"axis": "Standards", "blocking": False, "finding": large,
                       "path": "src/a.ts", "line": 2}]}
        files = p.plan(result, identity, {"posted": []}, "owner/repo")
        summary = "".join(body for name, body in sorted(files.items()) if name.endswith(".md"))
        self.assertIn("2 blocking, 1 advisory", summary)
        self.assertIn("1 finding in inline comments", summary)
        self.assertNotIn("inline bug", summary)
        self.assertIn("Spec: general requirement", summary)
        chunks = "".join(body.split("\n\n", 4)[-1] for name, body in sorted(files.items())
                         if name.endswith(".md"))
        self.assertIn(large, chunks)
        payload = json.loads(files["inline.json"])
        self.assertIn("inline bug", payload["comments"][0]["body"])
        self.assertNotIn("full report", payload["body"])
        # Already-published inline findings stay omitted on a publisher rerun.
        reviews = [[{"user": {"login": "github-actions[bot]", "type": "Bot"}, "body": payload["body"]}]]
        rerun = p.plan(result, identity, {"posted": []}, "owner/repo", reviews)
        self.assertNotIn("inline.json", rerun)
        self.assertEqual({name: body for name, body in files.items() if name.endswith(".md")}, rerun)

    def test_compact_summary_removes_only_matching_axis_severity_and_occurrence(self):
        identity = {"run": "1", "head": "a" * 40, "base": "b" * 40, "issues": [],
                    "summary_format": "compact"}
        result = {"findings": ["Standards: duplicate", "Standards: duplicate", "Spec: duplicate"],
                  "advisory": ["Standards: duplicate"], "inline": [
                      {"axis": "Standards", "blocking": True, "finding": "duplicate",
                       "path": "src/a.ts", "line": 1}]}
        summary = p.plan(result, identity, {"posted": []}, "owner/repo")["0001.md"]
        self.assertEqual(summary.count("**Blocking** — Standards: duplicate"), 1)
        self.assertIn("**Blocking** — Spec: duplicate", summary)
        self.assertIn("Advisory — Standards: duplicate", summary)

    def test_compact_digest_binds_full_inline_findings_despite_equal_counts(self):
        identity = {"run": "1", "head": "a" * 40, "base": "b" * 40, "issues": [],
                    "summary_format": "compact"}
        markers = []
        for finding in ("first bug", "different bug"):
            result = {"findings": ["Standards: " + finding], "advisory": [], "inline": [
                {"axis": "Standards", "blocking": True, "finding": finding,
                 "path": "src/a.ts", "line": 1}]}
            files = p.plan(result, identity, {"posted": []}, "owner/repo")
            markers.append(p.FINAL_MARKER.fullmatch(files["0001.md"].split("\n", 1)[0]))
        self.assertNotEqual(markers[0][2], markers[1][2])

    def test_oversized_inline_findings_do_not_require_unpublishable_inline_review(self):
        head = "a" * 40
        identity = {"run": "1", "head": head, "base": "b" * 40, "issues": []}
        result = {"findings": [], "advisory": ["large"], "inline": [
            {"axis": "Standards", "blocking": False, "finding": "x" * 60_001,
             "path": "src/a.ts", "line": 1}]}
        files = p.plan(result, identity, {"posted": []}, "owner/repo")
        self.assertNotIn("inline.json", files)
        marker = p.FINAL_MARKER.fullmatch(files["0001.md"].split("\n", 1)[0])
        self.assertEqual(marker[5], "none")
        record = [marker[1], marker[2], int(marker[3]), int(marker[4]), marker[5]]
        self.assertTrue(p.complete(head, [record], set()))

    def test_legacy_recovery_persists_completion_without_artifacts(self):
        head = "a" * 40
        identity = {"run": "1", "head": head, "base": "b" * 40, "issues": []}
        result = {"findings": [], "advisory": []}
        files = p.plan(result, identity, {"posted": []}, "owner/repo")
        marker = p.FINAL_MARKER.fullmatch(files["0001.md"].split("\n", 1)[0])
        legacy = [head, marker[2], 1, 1, None]
        upgrade = p.plan(result, identity, {"posted": [legacy]}, "owner/repo")
        self.assertIn("0001.md", upgrade)
        modern = [head, marker[2], 1, 1, "none"]
        self.assertTrue(p.complete(head, [legacy, modern], set()))
        self.assertEqual(p.plan(result, identity, {"posted": [legacy, modern]}, "owner/repo"), {})

    def test_completion_requires_every_part_and_matching_bot_inline(self):
        head, digest, inline = "a" * 40, "d" * 16, "e" * 16
        records = [[head, digest, part, 2, inline] for part in (1, 2)]
        self.assertFalse(p.complete(head, records, set()))
        self.assertFalse(p.complete(head, records[:1], {(head, inline)}))
        self.assertTrue(p.complete(head, records, {(head, inline)}))
        forged = [[{"user": {"login": "public", "type": "User"},
                    "body": f"<!-- tanomu-final-inline head={head} digest={inline} -->"}]]
        self.assertEqual(p.inline_markers(forged), set())
        # Large marker totals must not allocate a range-sized set.
        self.assertFalse(p.complete(head, [[head, digest, 1, 10**30, "none"]], set()))
