import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("publication", Path(__file__).with_name("publication.py"))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PublicationTest(unittest.TestCase):




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
