from pathlib import Path
from tempfile import TemporaryDirectory
import base64
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.notifications import CompletionTracker, SoundLibrary, completion_snapshot, windows_media_uri, windows_local_path
from backend.preferences import NotificationPreferences, Preferences
from backend.config import Settings
from backend.service import Studio
from backend.api import create_app
from .fakes import FakeCloud


def item(status="active",kind="image",**extra):
    return dict(status=status,kind=kind,name="test",**extra)


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=self.root/'observed.json';self.tracker=CompletionTracker(self.path)
        self.prefs=NotificationPreferences(enabled=True,mode="each")

    def tearDown(self):
        self.temp.cleanup()

    def test_media_uri_accepts_tauri_verbatim_paths_and_unicode(self):
        normal = "D:/文件/声音/a # 100%.wav"
        verbatim = "\\\\?\\D:\\文件\\声音\\a # 100%.wav"
        self.assertEqual(windows_media_uri(normal), windows_media_uri(verbatim))
        uri = windows_media_uri(verbatim)
        self.assertTrue(uri.startswith("file:///D:/"))
        self.assertIn("%23", uri)
        self.assertIn("100%25.wav", uri)
        unc = "\\\\?\\UNC\\server\\share\\sound.wav"
        self.assertEqual(windows_local_path(unc), "\\\\server\\share\\sound.wav")
        self.assertEqual(windows_media_uri(unc), "file://server/share/sound.wav")

    def test_terminal_history_is_not_replayed_and_each_completion_is_once(self):
        self.assertEqual(self.tracker.poll({'old':item('success')},self.prefs),[])
        self.tracker.poll({'old':item('success'),'new':item()},self.prefs)
        final={'old':item('success'),'new':item('success')}
        self.assertEqual(len(self.tracker.poll(final,self.prefs)),1)
        self.assertEqual(self.tracker.poll(final,self.prefs),[])
        self.assertEqual(CompletionTracker(self.path).poll(final,self.prefs),[])

    def test_all_waits_for_new_jobs_too_and_ignores_drafts(self):
        self.prefs.mode='all'
        self.tracker.poll({'a':item(),'draft':item('idle')},self.prefs)
        self.assertEqual(self.tracker.poll({'a':item('success'),'b':item(),'draft':item('idle')},self.prefs),[])
        result=self.tracker.poll({'a':item('success'),'b':item('success'),'draft':item('idle')},self.prefs)
        self.assertEqual([len(group) for group in result],[2])
        self.assertEqual(self.tracker.poll({'a':item('success'),'b':item('success')},self.prefs),[])

    def test_restart_preserves_unfinished_cohort(self):
        self.prefs.mode='all'
        self.tracker.poll({'a':item(),'b':item()},self.prefs)
        self.tracker.poll({'a':item('success'),'b':item()},self.prefs)
        restarted=CompletionTracker(self.path)
        result=restarted.poll({'a':item('success'),'b':item('success')},self.prefs)
        self.assertEqual([len(group) for group in result],[2])

    def test_disabled_scope_and_failures(self):
        self.tracker.poll({'a':item(),'b':item()},self.prefs)
        self.prefs.enabled=False
        self.assertEqual(self.tracker.poll({'a':item('success'),'b':item('failed')},self.prefs),[])
        self.prefs.enabled=True
        self.assertEqual(self.tracker.poll({'a':item('success'),'b':item('failed')},self.prefs),[])
        self.prefs.include_failures=False;self.prefs.harness_tasks=False
        self.tracker.poll({'fail':item(),'cancel':item(),'agent':item(kind='harness')},self.prefs)
        self.assertEqual(self.tracker.poll({'fail':item('failed'),'cancel':item('cancelled'),'agent':item('success',kind='harness')},self.prefs),[])

    def test_fast_completion_and_deleted_batch_do_not_stall(self):
        self.prefs.mode='all'
        self.tracker.poll({'a':item('idle'),'deleted':item()},self.prefs)
        self.assertEqual(len(self.tracker.poll({'a':item('success')},self.prefs)),1)

    def test_corrupt_auxiliary_state_never_breaks_studio(self):
        self.path.write_text('{broken')
        tracker=CompletionTracker(self.path)
        self.assertEqual(tracker.poll({'a':item('success')},self.prefs),[])
        self.assertTrue(self.path.with_name('observed-recovery.json').exists())

    def test_sound_is_copied_validated_and_bounded_to_managed_folder(self):
        sounds=SoundLibrary(self.root/'sounds')
        self.assertIsNone(sounds.resolve(NotificationPreferences(sound_enabled=False)))
        for builtin in ['soft','chime','double']:
            self.assertTrue(sounds.resolve(NotificationPreferences(sound=builtin)).is_file())
        data=(self.root/'sounds/soft.wav').read_bytes()
        imported=sounds.import_sound('../own.wav',base64.b64encode(data).decode())
        self.assertEqual(imported['custom_sound_name'],'own.wav')
        selected=NotificationPreferences(sound='custom',**imported)
        self.assertEqual(sounds.resolve(selected).read_bytes(),data)
        for name,data in [('x.exe',b'RIFF'),('x.wav',b'bad'),('x.mp3',b'bad')]:
            with self.assertRaises(ValueError):sounds.import_sound(name,base64.b64encode(data).decode())
        with self.assertRaises(ValueError):sounds.import_sound('x.mp3','!'*20)
        with self.assertRaises(ValueError):NotificationPreferences(custom_sound_id='../bad.wav')

    def test_harness_snapshot_waits_for_whole_run_not_model_step(self):
        from backend.harness_batch import HarnessBatch
        from backend.harness_models import HarnessRun
        from backend.harness_batch import canonical
        studio=Studio(Settings(self.root,self.root/'data'),FakeCloud())
        harness=HarnessBatch(studio)
        try:
            harness.create_run(HarnessRun(run_id='a'*64,session_id='s',workspace=str(self.root)))
            with harness.connection() as db:
                db.execute('INSERT INTO requests(id,run_id,data) VALUES (?,?,?)',('b'*64,'a'*64,canonical(dict(request_id='b'*64,run_id='a'*64,phase='completed',created_at='2026-10-15'))))
            key='harness:'+'a'*64
            self.assertEqual(completion_snapshot(studio,harness)[key]['status'],'active')
            harness.finish_run('a'*64)
            self.assertEqual(completion_snapshot(studio,harness)[key]['status'],'success')
        finally:harness.close();studio.close()

    def test_image_queue_finishes_independently_of_running_harness(self):
        self.prefs.mode='all'
        self.tracker.poll({'image':item(),'agent':item(kind='harness')},self.prefs)
        final={'image':item('success'),'agent':item(kind='harness')}
        self.assertEqual(self.tracker.poll(final,self.prefs),[[final['image']]])
        self.assertEqual(set(self.tracker.state['pending']),{'agent'})
        self.assertEqual(self.tracker.poll(final,self.prefs),[])
        final['agent']=item('success',kind='harness')
        self.assertEqual(self.tracker.poll(final,self.prefs),[[final['agent']]])

    def test_mixed_persisted_cohort_migrates_without_replaying_history(self):
        self.prefs.mode='all'
        original={'image':item(),'agent':item(kind='harness'),'old':item('success')}
        self.tracker.poll(original,self.prefs)
        final={**original,'image':item('success'),'agent':item('paused',kind='harness')}
        restarted=CompletionTracker(self.path)
        self.assertEqual(restarted.poll(final,self.prefs),[[final['image']]])
        self.assertEqual(restarted.state['pending'],{})
        self.assertEqual(CompletionTracker(self.path).poll(final,self.prefs),[])

    def test_pause_alone_never_emits_completion(self):
        for mode in ['all','each']:
            self.prefs.mode=mode
            self.tracker.poll({'agent':item(kind='harness')},self.prefs)
            final={'agent':item('paused',kind='harness')}
            self.assertEqual(self.tracker.poll(final,self.prefs),[])
            self.assertEqual(self.tracker.state['pending'],{})

    def test_simultaneous_queues_emit_separate_notifications_and_failures_respect_switch(self):
        self.prefs.mode='all';self.prefs.include_failures=False
        self.tracker.poll({'i':item(),'h':item(kind='harness'),'f':item()},self.prefs)
        result=self.tracker.poll({'i':item('success'),'h':item('success',kind='harness'),'f':item('failed')},self.prefs)
        self.assertEqual([[i['kind'] for i in group] for group in result],[['image'],['harness']])
        self.assertEqual(self.tracker.state['pending'],{})

    def test_paused_harness_snapshot_requires_real_inflight_cloud_work(self):
        from backend.harness_batch import HarnessBatch, canonical
        from backend.harness_models import HarnessRun
        studio=Studio(Settings(self.root,self.root/'data'),FakeCloud())
        harness=HarnessBatch(studio)
        run_id='a'*64;key='harness:'+run_id
        try:
            harness.create_run(HarnessRun(run_id=run_id,session_id='s',workspace=str(self.root)))
            harness.set_run_phase(run_id,'paused')
            def check(receipts, expected):
                with harness.connection() as db:
                    db.execute('DELETE FROM requests')
                    for n,receipt in enumerate(receipts):
                        ident=f'{n:064x}'
                        value=dict(request_id=ident,run_id=run_id,created_at='2026-10-15',**receipt)
                        db.execute('INSERT INTO requests(id,run_id,data) VALUES (?,?,?)',(ident,run_id,canonical(value)))
                self.assertEqual(completion_snapshot(studio,harness)[key]['status'],expected)
            check([], 'paused')
            check([dict(phase='completed')], 'paused')
            check([dict(phase='budget_paused')], 'paused')
            check([dict(phase='failed')], 'failed')
            check([dict(phase='completed',truncated=True)], 'failed')
            check([dict(phase='cancelled')], 'cancelled')
            check([dict(phase='monitoring'),dict(phase='completed')], 'active')
            check([dict(phase='submission_uncertain')], 'active')
        finally:harness.close();studio.close()

    def test_image_completion_reaches_native_dispatch_queue(self):
        import queue
        from types import SimpleNamespace
        from backend.notifications import NotificationCenter
        center=object.__new__(NotificationCenter)
        center.studio=SimpleNamespace(settings=SimpleNamespace(root=self.root))
        center.harness=object();center.tracker=self.tracker;center.work=queue.Queue()
        self.prefs.mode='all'
        with patch('backend.notifications.load_preferences',return_value=SimpleNamespace(notifications=self.prefs)):
            with patch('backend.notifications.completion_snapshot',return_value={'i':item(),'h':item(kind='harness')}):center.tick()
            with patch('backend.notifications.completion_snapshot',return_value={'i':item('success'),'h':item(kind='harness')}):center.tick()
        title,body,prefs=center.work.get_nowait()
        self.assertIn('生图',title)
        self.assertIn('1',body)
        self.assertTrue(center.work.empty())

    def test_old_preferences_defaults_and_owner_only_notification_routes(self):
        self.assertTrue(Preferences().notifications.enabled)
        self.assertFalse(Preferences.model_validate({"notifications":{"enabled":False}}).notifications.enabled)
        studio=Studio(Settings(self.root,self.root/'data'),FakeCloud())
        with patch('backend.api.secrets.token_urlsafe',return_value='scoped'):
            app=create_app(studio,'owner',background=False)
        with TestClient(app) as client:
            owner={'X-VBS-Token':'owner'};scoped={'X-VBS-Harness-Token':'scoped'}
            self.assertEqual(client.get('/notifications/status',headers=owner).status_code,200)
            self.assertEqual(client.get('/notifications/status',headers=scoped).status_code,401)
            self.assertEqual(client.post('/notifications/test',headers=scoped,json={}).status_code,401)
            prefs=client.get('/preferences',headers=owner).json()
            prefs['notifications']['enabled']=True
            self.assertEqual(client.put('/preferences',headers=owner,json=prefs).status_code,200)
            self.assertTrue(client.get('/preferences',headers=owner).json()['notifications']['enabled'])
            self.assertEqual(client.post('/notifications/sound',headers=owner,json={'name':'bad.wav','content_base64':'%%'}).status_code,400)
            self.assertEqual(client.post('/harness/ui/notification-settings',headers=scoped).status_code,200)
            self.assertEqual(client.get('/harness/status',headers=owner).json()['ui_request_tab'],'notifications')


if __name__=='__main__':unittest.main()
