import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core as RUN
from media import image_info, pdf_region

def issue():
    return {
        "date": "2026-10-18", "overview": "A real search found one relevant paper.",
        "search_notes": "Full text read.", "search_queries": ["onboard robotic catching"],
        "excluded_candidates": [], "papers": [{
            "id": "arxiv:2602.22733", "title": "Example", "authors": "A", "institutions": ["B"],
            "publication": "Preprint", "first_posted": "2026-02-26", "version_date": "2026-02-26",
            "category": "adjacent", "reading_level": "full_text",
            "arxiv_url": "https://arxiv.org/abs/2602.22733", "pdf_url": "https://arxiv.org/pdf/2602.22733",
            "project_url": "", "code_url": "", "formulation": "Catch an object.",
            "sensing_and_actions": "External RGB -> joints.",
            "pipeline": [{"stage": "Track", "method": "Segmentation", "input_output": "RGB -> box"}],
            "training": "Simulation", "results": [{"evidence": "Synthetic test fixture only.", "source_anchor": "Table 1"}],
            "analysis": "Test fixture.", "reviewer": {k: "Test fixture." for k in ["contribution", "strength", "evidence_gap", "comparison", "judgement"]},
            "openarm_relevance": "Test fixture.", "sources": ["https://arxiv.org/abs/2602.22733"],
        }],
    }

def resource():
    return {"id": "code:fixture", "title": "Code fixture", "kind": "code", "creator": "Fixture author",
            "affiliation": "Unverified", "published_at": "Unknown", "access_url": "https://example.com/repository",
            "related_paper_url": "", "source_level": "metadata_only", "summary": "Metadata fixture only.",
            "research_relevance": "Inspect available interfaces.", "judgement": "No reproduction claim.",
            "access_notes": "No implementation was inspected.", "sources": ["https://example.com/repository"]}

class DigestTests(unittest.TestCase):
    def setUp(self):
            self.temp = tempfile.TemporaryDirectory()
            self.root = Path(self.temp.name)
            self.patch = patch.object(RUN, "ROOT", self.root)
            self.patch.start()
            self.config = {"already_read": [], "max_papers": 3, "timezone": "America/New_York", "send_at": "08:30"}

    def tearDown(self):
            self.patch.stop()
            self.temp.cleanup()

    def test_canonical_arxiv_version(self):
            self.assertEqual(RUN.canonical_id("https://arxiv.org/pdf/2602.22733v2"), "arxiv:2602.22733")

    def test_accept_valid_and_empty_issue(self):
            RUN.validate_digest(issue(), self.config, "2026-10-18")
            empty = issue()
            empty["papers"] = []
            RUN.validate_digest(empty, self.config, "2026-10-18")

    def test_reject_wrong_date_or_abstract(self):
            with self.assertRaises(ValueError):
                RUN.validate_digest(issue(), self.config, "2026-10-19")
            data = issue()
            data["papers"][0]["reading_level"] = "abstract"
            with self.assertRaises(ValueError):
                RUN.validate_digest(data, self.config, "2026-10-18")

    def test_reject_wrong_arxiv_link(self):
            data = issue()
            data["papers"][0]["arxiv_url"] = "https://arxiv.org/abs/2409.10319"
            with self.assertRaises(ValueError):
                RUN.validate_digest(data, self.config, "2026-10-18")

    def test_reject_previously_read_title_and_id(self):
            self.config["already_read"] = [{"id": "arxiv:2602.22733v2", "title": "Example"}]
            with self.assertRaises(ValueError):
                RUN.validate_digest(issue(), self.config, "2026-10-18")
            self.config["already_read"][0]["id"] = "title:example"
            with self.assertRaises(ValueError):
                RUN.validate_digest(issue(), self.config, "2026-10-18")

    def test_dedup_requires_successful_delivery(self):
            folder = self.root / "archive/20261017"
            folder.mkdir(parents=True)
            RUN.write_json(folder / "digest.json", issue())
            self.assertEqual(RUN.seen_papers(self.config), [])
            RUN.write_json(folder / "receipt.json", {"status": "published"})
            self.assertEqual(RUN.seen_papers(self.config)[0]["id"], "arxiv:2602.22733")

    def test_renderer_escapes_source_text(self):
            data = issue()
            data["papers"][0]["title"] = "<script>alert(1)</script>"
            rendered = RUN.render(data, self.config)
            self.assertNotIn("<script>", rendered)
            self.assertIn("&lt;script&gt;", rendered)
            self.assertIn("Problem formulation", rendered)
            self.assertIn("Robotics reviewer judgment", rendered)
            self.assertNotIn('href="javascript:', RUN.rich_text("[bad](javascript:alert(1))"))

    def test_renderer_accepts_markdown_source_links(self):
            data = issue()
            data["papers"][0]["sources"] = ["[Official paper](https://arxiv.org/abs/2602.22733)"]
            RUN.validate_digest(data, self.config, "2026-10-18")
            rendered = RUN.render(data, self.config)
            self.assertIn('href="https://arxiv.org/abs/2602.22733">Official paper</a>', rendered)
            self.assertNotIn('href="[Official', rendered)

    def test_resource_only_issue_preserves_evidence_level(self):
            data = issue()
            data["papers"] = []
            data["resources"] = [resource()]
            RUN.validate_digest(data, self.config, "2026-10-18")
            rendered = RUN.render(data, self.config)
            self.assertIn("补充研究资源", rendered)
            self.assertIn("仅元信息", rendered)
            self.assertIn("对你的研究有什么用", rendered)
            self.assertIn('href="https://example.com/repository"', rendered)

    def test_resource_dedup_requires_delivery(self):
            data = issue()
            data["resources"] = [resource()]
            folder = self.root / "archive/20261017_resources"
            folder.mkdir(parents=True)
            RUN.write_json(folder / "digest.json", data)
            self.assertEqual(RUN.seen_resources(self.config), [])
            RUN.write_json(folder / "receipt.json", {"status": "published"})
            with self.assertRaises(ValueError):
                RUN.validate_digest(data, self.config, "2026-10-18")

    def test_resource_rejects_invalid_access_link(self):
            data = issue()
            data["resources"] = [resource()]
            data["resources"][0]["related_paper_url"] = "javascript:alert(1)"
            with self.assertRaises(ValueError):
                RUN.validate_digest(data, self.config, "2026-10-18")

    def test_required_paper_fields_are_not_empty_headings(self):
            for field in ["formulation", "analysis", "training"]:
                data = issue()
                data["papers"][0][field] = " "
                with self.assertRaises(ValueError):
                    RUN.validate_digest(data, self.config, "2026-10-18")

    def test_images_required_or_explicit_access_reason(self):
            data = issue()
            self.config["required_paper_figures"] = 2
            with self.assertRaises(ValueError):
                RUN.validate_digest(data, self.config, "2026-10-18")
            data["papers"][0]["figures_unavailable_reason"] = "Fixture: source is unavailable."
            RUN.validate_digest(data, self.config, "2026-10-18")

    def test_paper_analysis_precedes_supplementary_cards(self):
            data = issue()
            data["resources"] = [resource()]
            rendered = RUN.render(data, self.config)
            self.assertLess(rendered.index("Problem formulation"), rendered.index("补充研究资源"))

    def test_figure_is_inline_in_mail_and_local_in_preview(self):
            asset = {"owner_id": "arxiv:2602.22733", "role": "pipeline", "path": "media/pipeline.jpg",
                     "content_id": "fixture@digest", "width": 1000, "figure_label": "Fig. 2", "caption": "Fixture caption.",
                     "source_url": "https://example.com/paper.pdf#page=2"}
            mailed = RUN.render(issue(), self.config, assets=[asset])
            preview = RUN.render(issue(), self.config, assets=[asset], preview=True)
            self.assertIn("src='cid:fixture@digest'", mailed)
            self.assertIn("src='media/pipeline.jpg'", preview)
            self.assertIn("Fixture caption.", mailed)

    def test_html_error_page_is_not_accepted_as_a_figure(self):
            with self.assertRaises(ValueError):
                image_info(b"<html>403 Forbidden</html>")

    def test_pdf_crop_rejects_out_of_page_bounds(self):
            with self.assertRaises(ValueError):
                pdf_region(self.root / "absent.pdf", 1, [0, 0, 1.2, 1], self.root / "absent.jpg")
