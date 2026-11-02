from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock,patch
from backend.config import Settings
from backend.harness_runtime import HarnessRuntime,node_path

class HarnessRuntimeTests(TestCase):
    def test_windows_verbatim_paths_are_normalized_for_node_esm(self):
        self.assertEqual(str(node_path(r'\\?\D:\workspace\harness')),str(Path(r'D:\workspace\harness')))
        self.assertEqual(str(node_path(r'\\?\UNC\host\share\harness')),str(Path(r'\\host\share\harness')))
    def test_running_preview_cannot_silently_turn_into_cloud_mode(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            runtime=HarnessRuntime(Settings(root,root/'data'))
            runtime.child=SimpleNamespace(poll=lambda:None)
            runtime.offline=True
            with self.assertRaisesRegex(ValueError,'停止当前 Harness'):
                runtime.start('http://127.0.0.1:1','private-scoped-token',False)
    def test_shutdown_asks_plugin_to_dispose_before_force_kill(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            runtime=HarnessRuntime(Settings(root,root/'data'))
            child=MagicMock()
            child.poll.side_effect=[None,0,0]
            runtime.child=child
            with patch('backend.harness_runtime.subprocess.run') as force:
                runtime.close()
            child.stdin.write.assert_called_once_with('vbs-shutdown\n')
            child.stdin.flush.assert_called_once()
            force.assert_not_called()

    def test_frozen_runtime_prefers_bundled_component_and_keeps_legacy_fallback(self):
        import sys
        with TemporaryDirectory() as temp:
            root=Path(temp).resolve();installed=root/'application';data=root/'userdata'
            bundled=installed/'harness';bundled.mkdir(parents=True)
            runtime=HarnessRuntime(Settings(data,data/'data'))
            with patch.object(sys,'frozen',True,create=True), patch.object(sys,'executable',str(installed/'backend/vertex-backend.exe')):
                self.assertEqual(runtime.source,data/'components/harness')
                (bundled/'component-manifest.json').write_text('{}')
                self.assertEqual(runtime.source,bundled)

    def test_profile_can_be_generated_outside_readonly_runtime(self):
        import runpy
        generate=runpy.run_path(str(Path(__file__).resolve().parents[1]/'harness/setup_profile.py'))['generate']
        with TemporaryDirectory() as temp:
            root=Path(temp);component=root/'component'
            for name in ('base','web-app'):
                bundle=component/'upstream/node_modules/@deepseek-ai'/('dsh-'+name)
                bundle.mkdir(parents=True)
                (bundle/'cordis.patch.yml').write_text('[]')
            output=root/'user/.runtime/harness-profile.yml'
            self.assertEqual(generate(component,output=output),output)
            self.assertTrue(output.is_file())
            self.assertFalse((component/'studio.patch.yml').exists())

    def test_request_stop_blocks_new_start_and_force_kills_unresponsive_child(self):
        import subprocess
        with TemporaryDirectory() as temp:
            root=Path(temp)
            runtime=HarnessRuntime(Settings(root,root/'data'), instance_id='test-inst-1')
            runtime.request_stop()
            child=MagicMock()
            child.pid=999999
            child.poll.side_effect=[None,None,1]
            child.wait.side_effect=[subprocess.TimeoutExpired(cmd='node',timeout=4.5),1]
            runtime.child=child
            mock_job=MagicMock()
            mock_job.active_processes.side_effect=[1,0]
            mock_job.terminate.return_value=None
            runtime._job=mock_job
            with patch('backend.harness_runtime.subprocess.run') as force:
                force.return_value=SimpleNamespace(returncode=0,stderr='')
                runtime.close(timeout=2.0)
            mock_job.terminate.assert_called_once_with(1)
            force.assert_called_once()
            self.assertTrue(runtime.last_close_result['forced'])
            self.assertTrue((root/'.runtime/lifecycle.log').is_file())
            with self.assertRaisesRegex(ValueError,'正在退出'):
                runtime.start('http://127.0.0.1:1','private-scoped-token',True)

    def test_windows_job_object_kills_child_and_grandchild_on_close(self):
        import subprocess,sys,time
        from backend.lifecycle import WindowsJobObject,is_process_alive_with_identity,process_creation_filetime,process_executable_path,resume_process_handle,find_locking_processes
        if sys.platform!='win32':
            self.skipTest('Windows only')
        with TemporaryDirectory() as temp:
            root=Path(temp)
            pid_file=root/'grandchild.pid'
            locked_file=root/'locked.bin'
            locked_file.write_bytes(b'test')
            code=(
                "import subprocess,sys,time,pathlib\n"
                f"f=open({str(locked_file)!r},'rb')\n"
                "gc=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],creationflags=0x08000000)\n"
                f"pathlib.Path({str(pid_file)!r}).write_text(str(gc.pid))\n"
                "time.sleep(60)\n"
            )
            job=WindowsJobObject.create()
            child=subprocess.Popen([sys.executable,'-c',code],creationflags=0x08000000|0x00000004)
            try:
                job.assign_process_handle(int(child._handle))
                resume_process_handle(int(child._handle))
                deadline=time.monotonic()+10
                while not pid_file.exists() and time.monotonic()<deadline:
                    time.sleep(0.05)
                self.assertTrue(pid_file.exists())
                gc_pid=int(pid_file.read_text().strip())
                child_ft=process_creation_filetime(child.pid)
                child_exe=process_executable_path(child.pid)
                self.assertTrue(is_process_alive_with_identity(child.pid,child_ft,child_exe))
                self.assertGreaterEqual(job.active_processes() or 0,2)
                holders=find_locking_processes([locked_file])
                self.assertTrue(any(h['pid']==child.pid for h in holders))
                # Closing the job handle must kill both child and grandchild via KILL_ON_JOB_CLOSE
                job.close()
                child.wait(timeout=5)
                deadline=time.monotonic()+5
                while is_process_alive_with_identity(gc_pid) and time.monotonic()<deadline:
                    time.sleep(0.05)
                self.assertFalse(is_process_alive_with_identity(child.pid,child_ft,child_exe))
                self.assertFalse(is_process_alive_with_identity(gc_pid))
            finally:
                job.close()
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)

