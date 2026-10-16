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
