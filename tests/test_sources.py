import unittest
from unittest.mock import patch
from sources import PageText, arxiv
from cloud import finalize_coverage
from test_core import issue, resource


class SourceTests(unittest.TestCase):
    def test_old_paper_is_labelled_older_but_recent_revision_is_preserved(self):
        data = issue()
        data['papers'][0]['category'] = 'core'
        evidence = {'sources': [], 'failures': []}
        finalize_coverage(data, evidence)
        self.assertEqual(data['papers'][0]['category'], 'foundational')
        data['papers'][0].update(category='update', version_date='2026-10-17')
        finalize_coverage(data, evidence)
        self.assertEqual(data['papers'][0]['category'], 'update')

    def test_overview_uses_reviewed_evidence_and_unwatched_talk_stays_metadata(self):
        data = issue()
        data['overview'] = 'Unverified discovery claim, not reviewed paper evidence.'
        entry = resource()
        entry.update(kind='talk', source_level='full_text')
        data['resources'] = [entry]
        finalize_coverage(data, {'sources': [{'papers': [{'title': 'Synthetic fixture'}]}], 'failures': []})
        self.assertNotIn('Unverified discovery claim', data['overview'])
        self.assertIn(data['papers'][0]['formulation'], data['overview'])
        self.assertEqual(data['resources'][0]['source_level'], 'metadata_only')
        self.assertIn('未观看或听取内容', data['resources'][0]['access_notes'])

    def test_visible_page_text_and_original_relative_link_resolution(self):
        page = PageText('https://arxiv.org/html/2602.22733v1')
        page.feed('<head><title>Hidden boilerplate</title></head><script>private script text</script>'
                  '<h1>Fixture paper</h1><a href="2602.22733v1/figures/overview.png">Original figure</a>'
                  '<iframe src="https://www.youtube.com/embed/fixture"></iframe>')
        self.assertNotIn('private script text', page.text)
        self.assertIn('Fixture paper', page.text)
        self.assertEqual(page.links[0], 'https://arxiv.org/html/2602.22733v1/figures/overview.png')
        self.assertIn('https://www.youtube.com/embed/fixture', page.links)

    def test_arxiv_dates_and_versioned_pdf_are_preserved_from_atom(self):
        fixture = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <id>http://arxiv.org/abs/2602.22733v2</id><title>Synthetic\nfixture</title>
        <published>2026-02-26T00:00:00Z</published><updated>2026-03-01T00:00:00Z</updated>
        <summary>Not scientific evidence.</summary><author><name>Fixture author</name></author>
        </entry></feed>'''
        with patch('sources.fetch', return_value=fixture):
            data = arxiv('fixture query')
        paper = data['papers'][0]
        self.assertEqual(paper['title'], 'Synthetic fixture')
        self.assertEqual(paper['pdf_url'], 'https://arxiv.org/pdf/2602.22733v2')
        self.assertEqual(paper['published'], '2026-02-26T00:00:00Z')
        self.assertEqual(data['reading_level'], 'abstract_metadata')
