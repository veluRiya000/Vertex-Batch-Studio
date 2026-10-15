from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from harness.setup_profile import generate

class HarnessComponentTests(unittest.TestCase):
    def fixture(self, root, flattened):
        for bundle in ("base", "web-app"):
            directory = root / ("upstream/node_modules/@deepseek-ai/dsh-" + bundle if flattened else "upstream/packages/bundle/" + bundle)
            directory.mkdir(parents=True)
            (directory / "cordis.patch.yml").write_text("- insert:\n    - id: subagent\n    - id: office-to-pdf\n    - id: deepseek-account\n    - id: session-telemetry-otel\n    - id: schedule\n", encoding="utf-8")
            if bundle == "web-app":
                (directory / "presets").mkdir()
                (directory / "presets/standard.patch.yml").write_text("- insert:\n    - id: preset-standard\n    - id: preset-ptc\n    - id: preset-minimal\n", encoding="utf-8")
        text = generate(root).read_text(encoding="utf-8")
        return json.loads(text.replace("!!js process.env.VBS_HARNESS_WORKSPACE_PARENT", '\"workspace\"'))

    def test_removed_services_and_nested_presets_disabled(self):
        with TemporaryDirectory() as temp:
            rows = self.fixture(Path(temp), False)
            disabled = {r["id"] for r in rows if r.get("disabled")}
            self.assertTrue({"subagent", "office-to-pdf", "deepseek-account", "session-telemetry-otel", "schedule", "preset-ptc", "preset-minimal"} <= disabled)
            preset = next(r["config"] for r in rows if r.get("id") == "preset-standard")
            encoded = json.dumps(preset)
            self.assertNotIn("subagent", encoded)
            self.assertNotIn("tool-workflow", encoded)
            self.assertIn("tool-pwsh", encoded)
            self.assertIn("tool-skill", encoded)
            self.assertIn("planMode", encoded)
            self.assertIn("toolResultPruner", encoded)

    def test_flattened_component_paths_regenerate_after_install(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            rows = self.fixture(root, True)
            inserted = next(r["insert"] for r in rows if "insert" in r)
            self.assertEqual(inserted[0]["name"], (root / "plugins/vertex-batch/index.mjs").as_posix())

if __name__ == "__main__":
    unittest.main()
