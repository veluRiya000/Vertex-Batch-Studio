"""No cloud calls: regressions for long-lived clients, fallback data and image repair."""
import asyncio
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import threading
import unittest
from unittest.mock import Mock, patch

import httpx
from backend.api import create_app
from backend.config import Settings
from backend.files import read_json
from backend.model_catalog import OfficialCatalogue, maintained_models, navigation_candidates
from backend.models import TaskInput
from backend.service import Studio
from tests.fakes import FakeCloud, image_bytes


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cloud = FakeCloud()
        self.studio = Studio(Settings(self.root, self.root / 'data', project='demo', bucket='bucket'), self.cloud)

    def tearDown(self):
        self.studio.close()
        self.temp.cleanup()

    def batch(self):
        batch = self.studio.repo.create('test')
        self.studio.append_task(batch['id'], TaskInput(name='test', prompt='draw'))
        return batch['id']

    def test_expired_credentials_before_create_are_retryable_not_unknown(self):
        bid = self.batch()
        self.cloud.prepare_submission = Mock(side_effect=TimeoutError('refresh failed'))
        with self.assertRaises(TimeoutError):
            self.studio.submit(bid)
        self.assertEqual(self.studio.repo.get(bid)['phase'], 'submission_failed')
        self.assertEqual(self.cloud.creates, 0)
        self.cloud.prepare_submission = Mock()
        self.assertTrue(self.studio.submit(bid)['job_name'])
        self.assertEqual(self.cloud.creates, 1)

    def test_unconfirmed_submission_does_not_create_again_and_can_be_reconciled(self):
        bid = self.batch()
        self.studio.prepare(bid)
        batch = self.studio.repo.get(bid)
        batch.update(phase='submission_unknown', submission_started_at='2020-01-01T00:00:00+08:00')
        self.studio.repo.save(batch)
        self.assertEqual(self.studio.poll(bid)['phase'], 'submission_unconfirmed')
        self.studio.submit(bid)
        self.assertEqual(self.cloud.creates, 0)
        manifest = self.studio.manifest(bid)
        job = self.cloud.create_job(manifest['model'], manifest['input_uri'], manifest['output_prefix'], 'vbs-' + bid)
        self.assertEqual(self.studio.poll(bid)['job_name'], job.name)
        self.assertEqual(self.cloud.creates, 1)

    def test_category_removal_keeps_files_references_and_cross_folder_order(self):
        refs = []
        for category in ['characters', 'styles']:
            image = self.root / (category + '.png')
            image.write_bytes(image_bytes((1, 2, 3)))
            refs.append(self.studio.assets.import_file(str(image), category=category)['path'])
        bid = self.batch()
        self.studio.append_task(bid, TaskInput(name='refs', prompt='draw', refs=refs))
        for category in ['characters', 'styles']:
            self.studio.assets.delete_category(category)
        self.assertTrue(all((self.studio.settings.data_dir / ref).is_file() for ref in refs))
        self.assertEqual(self.studio.repo.tasks(bid)[1].refs, refs)
        expected = list(reversed(refs))
        self.assertEqual([r['path'] for r in self.studio.assets.reorder('uncategorized', expected)], expected)
        created = self.studio.assets.add_category('新分类')
        self.assertTrue(any(item['label'] == '新分类' for item in created))
        self.assertEqual(self.studio.assets.categories(), created)

    def test_move_reference_preserves_live_paths_and_prunes_uncategorized(self):
        image = self.root / 'person.png'
        image.write_bytes(image_bytes((1, 2, 3)))
        assets = self.studio.assets
        ref = assets.import_file(str(image), category='characters')['path']
        bid = self.batch()
        self.studio.append_task(bid, TaskInput(name='refs', prompt='draw', refs=[ref]))
        assets.delete_category('characters')
        self.assertIn('uncategorized', {v['id'] for v in assets.categories()})
        moved = assets.move(ref, 'styles')
        self.assertNotIn('uncategorized', {v['id'] for v in moved['categories']})
        self.assertEqual(moved['references'][0]['path'], ref)
        self.assertEqual(moved['references'][0]['category_id'], 'styles')
        self.assertTrue((self.studio.settings.data_dir / ref).is_file())
        self.assertEqual(self.studio.repo.tasks(bid)[1].refs, [ref])
        from backend.assets import Assets
        self.assertEqual(Assets(self.studio.repo).categories(), moved['categories'])

    def test_uncategorized_can_receive_import_and_delete_into_another_category(self):
        image = self.root / 'person.png'
        image.write_bytes(image_bytes((1, 2, 3)))
        assets = self.studio.assets
        original = assets.import_file(str(image), category='characters')['path']
        assets.delete_category('characters')
        imported = assets.import_file(str(image), category='uncategorized')['path']
        self.assertNotEqual(original, imported)
        with self.assertRaises(ValueError):
            assets.delete_category('uncategorized')
        categories = assets.delete_category('uncategorized', 'styles')
        self.assertNotIn('uncategorized', {v['id'] for v in categories})
        self.assertEqual({v['category_id'] for v in assets.list()}, {'styles'})
        for ref in (original, imported):
            self.assertTrue((self.studio.settings.data_dir / ref).is_file())

    def test_deleting_last_uncategorized_image_does_not_recreate_tab_on_restart(self):
        image = self.root / 'person.png'
        image.write_bytes(image_bytes((1, 2, 3)))
        assets = self.studio.assets
        ref = assets.import_file(str(image), category='characters')['path']
        assets.delete_category('characters')
        self.assertEqual(assets.delete(ref), [])
        (self.studio.settings.data_dir / ref).write_bytes(b'broken image')
        from backend.assets import Assets
        self.assertNotIn('uncategorized', {v['id'] for v in Assets(self.studio.repo).categories()})
        self.assertEqual(assets.list(), [])
        for category in assets.categories():
            assets.delete_category(category['id'])
        self.assertEqual(Assets(self.studio.repo).categories(), [])

    def test_reimport_moved_image_keeps_each_logical_category_and_rejects_bad_targets(self):
        image = self.root / 'person.png'
        image.write_bytes(image_bytes((1, 2, 3)))
        assets = self.studio.assets
        ref = assets.import_file(str(image), category='characters')['path']
        assets.move(ref, 'styles')
        second = assets.import_file(str(image), category='characters')['path']
        self.assertNotEqual(ref, second)
        self.assertEqual({v['path']: v['category_id'] for v in assets.list()}, {ref:'styles', second:'characters'})
        with self.assertRaises(ValueError):
            assets.move(ref, 'missing')
        with self.assertRaises(ValueError):
            assets.move('../person.png', 'styles')

    def test_category_move_api_and_receiving_category_delete(self):
        image = self.root / 'person.png'
        image.write_bytes(image_bytes((1, 2, 3)))
        ref = self.studio.assets.import_file(str(image), category='characters')['path']
        app = create_app(self.studio, 'test', background=False)
        async def check():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1', headers={'X-VBS-Token':'test'}) as client:
                response = await client.post('/references/move', json={'path':ref, 'category':'styles'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['references'][0]['category_id'], 'styles')
                self.assertEqual((await client.delete('/references/categories/styles')).status_code, 200)
                self.assertEqual((await client.delete('/references/categories/uncategorized')).status_code, 400)
                response = await client.delete('/references/categories/uncategorized?move_to=scenes')
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('uncategorized', {v['id'] for v in response.json()})
                self.assertEqual((await client.get('/references')).json()[0]['category_id'], 'scenes')
        asyncio.run(check())

    def test_bundled_and_online_catalogue_are_validated_data(self):
        value = read_json(Path(__file__).parents[1] / 'backend/model-catalog.json')
        self.assertGreaterEqual(len(maintained_models(value, 'global')), 3)
        source = OfficialCatalogue()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = [json.dumps(value).encode()]
        with patch.object(source, '_discover_official', side_effect=ValueError('HTML changed')), patch('backend.model_catalog.requests.get', return_value=response):
            self.assertEqual(source.discover(self.studio.settings), maintained_models(value, 'global'))
            self.assertEqual(source.directory_source, 'maintained')
        malicious = copy.deepcopy(value)
        malicious['models'][0]['source_url'] = 'https://example.com/payload.py'
        with self.assertRaises(ValueError):
            maintained_models(malicious, 'global')
        self.assertEqual(len(navigation_candidates('<devsite-book-nav><a href="/gemini-enterprise-agent-platform/models/gemini/future">model</a></devsite-book-nav>')), 1)

    def test_overlapping_connection_checks_share_one_probe(self):
        calls = []
        def probe(bucket):
            calls.append(bucket)
            time.sleep(.08)
            return {'storage_connection': 'ok'}
        self.cloud.check_connection = probe
        app = create_app(self.studio, 'test', background=False)
        async def check():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1', headers={'X-VBS-Token':'test'}) as client:
                responses = await asyncio.gather(*[client.post('/cloud/check') for _ in range(8)])
                self.assertTrue(all(r.status_code == 200 for r in responses))
        asyncio.run(check())
        self.assertEqual(calls, ['bucket'])

    def test_exit_does_not_wait_for_upload_or_create_new_cloud_job(self):
        bid = self.batch()
        entered = threading.Event()
        release = threading.Event()
        original_upload = self.cloud.upload
        def upload(*args):
            entered.set()
            release.wait(3)
            return original_upload(*args)
        self.cloud.upload = upload
        try:
            self.studio.enqueue(bid, 'submit')
            self.assertTrue(entered.wait(2))
            started = time.monotonic()
            self.studio.close(wait=False)
            self.assertLess(time.monotonic() - started, .5)
            self.assertFalse(self.studio.enqueue(bid, 'submit'))
        finally:
            release.set()
            self.studio.close()
        self.assertEqual(self.cloud.creates, 0)
        self.assertEqual(self.studio.repo.get(bid)['phase'], 'uploading')
        self.assertEqual(len(self.studio.repo.tasks(bid)), 1)
        restored = Studio(self.studio.settings, self.cloud)
        try:
            self.assertTrue(restored.submit(bid)['job_name'])
            self.assertEqual(self.cloud.creates, 1)
        finally:
            restored.close()

    def test_harness_shutdown_cancels_queued_callbacks_without_lock_inversion(self):
        from backend.harness_batch import HarnessBatch
        broker = HarnessBatch(self.studio)
        release = threading.Event()
        entered = [threading.Event(), threading.Event()]
        def active(index):
            entered[index].set()
            release.wait(3)
        try:
            for index in range(2):
                broker._pool.submit(active, index)
            self.assertTrue(all(event.wait(1) for event in entered))
            queued = broker._pool.submit(lambda: None)
            def callback(_):
                with broker._lock:
                    pass
            queued.add_done_callback(callback)
            started = time.monotonic()
            broker.close(wait=False)
            self.assertLess(time.monotonic() - started, .5)
            self.assertTrue(queued.cancelled())
        finally:
            release.set()
            broker.close()


if __name__ == '__main__':
    unittest.main()
