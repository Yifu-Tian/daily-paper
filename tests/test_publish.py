import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import core
import run
from formatting import markdown
from test_core import issue


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / 'archive/20261019_sample'
        self.folder.mkdir(parents=True)
        self.root_patch = patch.object(core, 'ROOT', self.root)
        self.root_patch.start()
        self.config = {'repository': 'example/radar', 'assignee': 'reader'}
        data = issue()
        data['papers'][0]['formulation'] += ' Fixture @other_reader. [Channel](https://www.youtube.com/@fixture)'
        data['papers'][0].update(figures=[], figures_unavailable_reason='Synthetic fixture only.')
        self.assets = [{'owner_id': data['papers'][0]['id'], 'role': 'pipeline', 'path': 'media/fixture.jpg',
                        'figure_label': 'Fixture figure', 'caption': 'Synthetic fixture, not paper evidence.',
                        'source_url': 'https://example.com/paper.pdf'}]
        (self.folder / 'digest.md').write_text(markdown(data, self.assets))
        core.write_json(self.folder / 'media.json', self.assets)
        core.write_json(self.folder / 'prepared.json', {'sample': True})

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def test_bot_publication_keeps_full_content_and_immutable_image_links(self):
        created = {}
        def api(path, method='GET', payload=None):
            if '?' in path:
                return []
            if method == 'POST':
                created.update(payload)
                return {'number': 7}
            return {'number': 7, 'body': created['body'], 'assignees': [{'login': 'reader'}],
                    'user': {'login': 'github-actions[bot]'}, 'html_url': 'https://github.com/example/radar/issues/7',
                    'created_at': '2026-10-19T08:30:00-04:00'}
        with patch.object(run, 'github', side_effect=api), patch.object(run.subprocess, 'check_output', return_value='abc123\n'):
            run.publish(self.folder, self.config, '2026-10-19', True)
        self.assertIn('raw.githubusercontent.com/example/radar/abc123/archive/20261019_sample/media/fixture.jpg', created['body'])
        self.assertIn('@reader 今天的图文研究日报', created['body'])
        self.assertIn('@\u200bother_reader', created['body'])
        self.assertIn('https://www.youtube.com/@fixture', created['body'])
        for field in ['Problem formulation', 'Pipeline', '训练数据与监督', '实验结果及分析', 'Robotics reviewer judgment']:
            self.assertIn(field, created['body'])
        receipt = core.read_json(self.folder / 'receipt.json')
        self.assertEqual(receipt['publisher'], 'github-actions[bot]')
        self.assertFalse(receipt['email_delivery_verified'])

    def test_replay_of_completed_publication_does_not_call_api(self):
        core.write_json(self.folder / 'receipt.json', {'url': 'https://example.com/fixture'})
        with patch.object(run, 'github', side_effect=AssertionError('Must not duplicate')):
            run.publish(self.folder, self.config, '2026-10-19', True)

    def test_interrupted_publication_is_reconciled_before_post(self):
        previous = {'number': 7, 'body': '<!-- ego-catching-digest:20261019_sample -->',
                    'assignees': [{'login': 'reader'}], 'user': {'login': 'github-actions[bot]'},
                    'html_url': 'https://example.com/fixture', 'created_at': '2026-10-19T08:30:00-04:00'}
        with patch.object(run, 'github', side_effect=[[previous], previous]) as api:
            run.publish(self.folder, self.config, '2026-10-19', True)
        self.assertEqual(api.call_count, 2)
        self.assertTrue((self.folder / 'receipt.json').is_file())
