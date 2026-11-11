import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import paths
import services
from store import State


class LayoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "install"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, "utf-8")
        return target

    def test_new_install_keeps_state_and_runtime_separate(self):
        layout = paths.prepare_layout(self.root)
        self.assertEqual(layout.python, self.root / "program/runtime/python/python.exe")
        self.assertEqual(layout.astrbot_data, self.root / "userdata/astrbot/data")
        state = State.load(self.root)
        state.data["owner_qq"] = "123456"
        state.save()
        self.assertTrue((self.root / "userdata/state.json").exists())
        self.assertFalse((self.root / "state.json").exists())

    def test_interrupted_directory_creation_can_resume(self):
        paths._write_marker(self.root)
        layout = paths.prepare_layout(self.root)
        self.assertTrue(layout.program.is_dir())
        self.assertTrue(layout.data.is_dir())

    def legacy(self):
        self.write("state.json", json.dumps({"pids": {}, "done": ["extract", "ports", "configs", "import", "login"],
                                              "secrets": {"deepseek": "encrypted-sample"}}))
        self.write("astrbot/main.py", "program")
        self.write("astrbot/data/chat.db", "personal conversation")
        self.write("pack/persona/character.md", "edited persona")
        self.write("napcat-data/config/webui.json", "saved config")

    def test_migration_retains_originals_and_personal_data(self):
        self.legacy()
        layout = paths.prepare_layout(self.root)
        self.assertEqual((layout.astrbot / "main.py").read_text(), "program")
        self.assertFalse((layout.astrbot / "data").exists())
        self.assertEqual((layout.astrbot_data / "chat.db").read_text(), "personal conversation")
        self.assertEqual((layout.pack / "persona/character.md").read_text(), "edited persona")
        self.assertTrue((self.root / "astrbot/data/chat.db").exists())
        state = json.loads(layout.state_file.read_text())
        self.assertEqual(state["done"], ["extract", "ports"])
        self.assertEqual(state["secrets"]["deepseek"], "encrypted-sample")
        self.assertEqual(paths.prepare_layout(self.root).data, layout.data)

    def test_failed_copy_does_not_activate_partial_migration(self):
        self.legacy()
        with mock.patch.object(paths.shutil, "copytree", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                paths.prepare_layout(self.root)
        self.assertFalse((self.root / paths.MARKER).exists())
        self.assertFalse((self.root / "program").exists())
        self.assertTrue((self.root / "astrbot/data/chat.db").exists())

    def test_running_legacy_install_is_untouched(self):
        self.legacy()
        self.write("state.json", json.dumps({"pids": {"astrbot": 111}}))
        with mock.patch.object(services, "is_running", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "仍在运行"):
                paths.prepare_layout(self.root)
        self.assertFalse((self.root / paths.MARKER).exists())

    def test_outside_and_root_paths_are_rejected(self):
        for target in (self.root, self.root.parent / "outside", self.root / "../outside"):
            with self.assertRaises(ValueError):
                paths.assert_owned_path(target, self.root)

    def test_astrbot_starts_with_separate_data_and_static_assets(self):
        layout = paths.prepare_layout(self.root)
        (layout.astrbot / "data/dist").mkdir(parents=True)
        with mock.patch.object(services, "_spawn", return_value=100) as spawn:
            services.start_astrbot(layout, State.load(self.root))
        args = spawn.call_args.args
        self.assertEqual(args[2], layout.astrbot_root)
        self.assertEqual(args[3]["ASTRBOT_ROOT"], str(layout.astrbot_root))
        self.assertIn("--webui-dir", args[1])


if __name__ == "__main__":
    unittest.main()
