import threading
import time
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import Mock
import httpx
from backend.cloud import GoogleCloud
from backend.config import Settings
from backend.service import Studio
from backend.models import TaskInput
from tests.fakes import FakeCloud


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name)
        self.cloud=FakeCloud();self.studio=Studio(Settings(self.root,self.root/'data',project='demo',bucket='bucket'),self.cloud)
        self.bid=self.studio.repo.create('test')['id']
        self.task=self.studio.append_task(self.bid,TaskInput(name='test',prompt='original prompt'))

    def tearDown(self):
        self.studio.close();self.temp.cleanup()

    def unknown(self,accepted=False):
        if accepted:self.cloud.create_timeout=True
        else:self.cloud.create_error=httpx.ReadError('EOF')
        with self.assertRaises((httpx.ReadError,TimeoutError)):self.studio.submit(self.bid)
        self.cloud.create_error=None

    def test_network_restored_not_found_retries_original_round(self):
        self.unknown()
        self.studio.recover(self.bid)
        self.assertIsNotNone(self.studio.repo.get(self.bid)['job_name'])
        self.assertEqual(len(self.cloud.jobs),1)
        task=self.studio.repo.tasks(self.bid)[0]
        self.assertEqual(task.id,self.task['id']);self.assertEqual(task.prompt,'original prompt')

    def test_found_job_attaches_without_second_create(self):
        self.unknown(accepted=True)
        self.studio.recover(self.bid)
        self.assertEqual(self.cloud.creates,1)
        self.assertIsNotNone(self.studio.repo.get(self.bid)['job_name'])

    def test_lookup_failure_requires_explicit_confirmation(self):
        self.unknown()
        self.cloud.find_jobs=Mock(side_effect=TimeoutError('offline'))
        self.studio.recover(self.bid)
        batch=self.studio.repo.get(self.bid)
        self.assertEqual(batch['reconciliation_status'],'failed')
        self.assertEqual(batch['phase'],'submission_unconfirmed')
        self.assertEqual(self.cloud.creates,1)
        self.studio.recover_force(self.bid)
        self.assertEqual(len(self.cloud.jobs),1)
        self.assertEqual(self.cloud.find_jobs.call_count,1)

    def test_upload_failure_retries_and_connect_failure_is_retryable(self):
        self.cloud.upload_error=True
        with self.assertRaises(ConnectionError):self.studio.submit(self.bid)
        self.assertEqual(self.studio.repo.get(self.bid)['phase'],'upload_failed')
        self.cloud.upload_error=False;self.cloud.create_error=httpx.ConnectError('connect failed')
        with self.assertRaises(httpx.ConnectError):self.studio.submit(self.bid)
        self.assertEqual(self.studio.repo.get(self.bid)['phase'],'submission_failed')
        self.cloud.create_error=None;self.studio.submit(self.bid)
        self.assertEqual(len(self.cloud.jobs),1)

    def test_multiple_matches_do_not_resubmit_even_with_force(self):
        self.unknown(accepted=True)
        manifest=self.studio.manifest(self.bid)
        self.cloud.create_job(manifest['model'],manifest['input_uri'],manifest['output_prefix'],'vbs-'+self.bid)
        self.studio.recover_force(self.bid)
        self.assertEqual(self.cloud.creates,2)
        self.assertEqual(self.studio.repo.get(self.bid)['reconciliation_status'],'multiple')

    def test_active_operation_is_exposed_and_duplicate_click_does_not_enqueue(self):
        entered=threading.Event();release=threading.Event()
        original=self.cloud.create_job
        def create(*args):entered.set();release.wait(2);return original(*args)
        self.cloud.create_job=create
        try:
            self.assertTrue(self.studio.enqueue(self.bid,'submit'))
            self.assertTrue(entered.wait(1))
            self.assertEqual(self.studio.batch_status(self.studio.repo.get(self.bid))['active_action'],'submit')
            self.assertFalse(self.studio.enqueue(self.bid,'poll'))
        finally:release.set()
        deadline=time.monotonic()+2
        while self.studio.batch_status(self.studio.repo.get(self.bid))['active_action'] and time.monotonic()<deadline:time.sleep(.01)
        self.assertIsNone(self.studio.batch_status(self.studio.repo.get(self.bid))['active_action'])

    def test_lookup_deadline_releases_caller_and_reuses_inflight_read(self):
        client=GoogleCloud.__new__(GoogleCloud)
        client._lookup_lock=threading.Lock();client._lookups={};client.lookup_timeout=.02
        release=threading.Event()
        client._find_jobs=Mock(side_effect=lambda *args: (release.wait(2),[])[1])
        try:
            started=time.monotonic()
            for _ in range(2):
                with self.assertRaises(TimeoutError):client.find_jobs('name','uri')
            self.assertLess(time.monotonic()-started,.5)
            self.assertEqual(client._find_jobs.call_count,1)
        finally:release.set()

