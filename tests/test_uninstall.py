import base64
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import services
import uninstall
from paths import initialize_layout
from store import State


class UninstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "DaFeiYu"
        initialize_layout(self.root)
        self.home = self.base / "home"
        self.home.mkdir()
        self.desktop = self.base / "desktop"
        self.desktop.mkdir()
        self.state = State.load(self.root)
        self.state.data["pids"] = {"astrbot": 123, "napcat": 456}
        self.state.save()
        self.tencent = self.base / "Tencent Files"
        self.tencent.mkdir()
        (self.tencent / "chats.db").write_bytes(b"personal chats")

    def tearDown(self):
        self.tmp.cleanup()

    def run_uninstall(self, popen=None):
        popen = popen or mock.MagicMock()
        with mock.patch.object(services, "is_running", return_value=False), \
             mock.patch.object(services, "tencent_roots", return_value=[self.tencent]) as roots, \
             mock.patch.object(uninstall.subprocess, "Popen", popen), \
             mock.patch.object(uninstall.tempfile, "gettempdir", return_value=str(self.base)):
            script = uninstall.uninstall(self.root, self.state, home=self.home, desktop=self.desktop)
            roots.assert_not_called()
        return script, popen

    def spec(self, script):
        encoded = re.search(r"FromBase64String\('([^']+)'\)", script.read_text(encoding="utf-8-sig"))[1]
        return json.loads(base64.b64decode(encoded))

    def test_stops_services_and_preserves_external_qq(self):
        script, _ = self.run_uninstall()
        self.assertEqual(self.state.data["pids"], {})
        self.assertEqual((self.tencent / "chats.db").read_bytes(), b"personal chats")
        self.assertTrue(self.home.is_dir())
        self.assertEqual(uninstall.leftovers(self.root, self.state, self.home), [self.root])

    def test_cleanup_uses_literal_paths_and_encoded_command(self):
        script, popen = self.run_uninstall()
        text = script.read_text(encoding="utf-8-sig")
        spec = self.spec(script)
        self.assertEqual(spec["root"], str(self.root))
        self.assertEqual(spec["remember"], str(self.home / "install.json"))
        self.assertNotIn("Tencent Files", json.dumps(spec))
        self.assertIn("Remove-Item -LiteralPath $target", text)
        self.assertIn("ReparsePoint", text)
        argv = popen.call_args.args[0]
        self.assertEqual(argv[0], "powershell")
        self.assertEqual(base64.b64decode(argv[-1]).decode("utf-16-le"), text)
        self.assertIn("Hidden", argv)
        self.assertTrue(popen.call_args.kwargs["creationflags"] & services.CREATE_NO_WINDOW)

    def test_unknown_root_rejected_before_stopping_services(self):
        foreign = self.base / "foreign"
        foreign.mkdir()
        (foreign / "state.json").write_text("{}")
        with mock.patch.object(services, "stop_all") as stop:
            with self.assertRaises(ValueError):
                uninstall.uninstall(foreign, self.state, home=self.home, desktop=self.desktop)
            stop.assert_not_called()

    def test_linked_root_rejected(self):
        with mock.patch.object(uninstall.checks, "has_link", return_value=True), \
             mock.patch.object(services, "stop_all") as stop:
            with self.assertRaises(ValueError):
                uninstall.uninstall(self.root, self.state)
            stop.assert_not_called()

    def test_cleanup_script_parses_without_execution(self):
        script, _ = self.run_uninstall()
        command = ("$t=$null;$e=$null;[System.Management.Automation.Language.Parser]::ParseFile("
                   "$env:DF_TEST_SCRIPT,[ref]$t,[ref]$e)|Out-Null;if($e.Count){$e|Out-String;exit 1}")
        import os
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                                env=dict(os.environ, DF_TEST_SCRIPT=str(script)), capture_output=True,
                                creationflags=services.CREATE_NO_WINDOW, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8", "replace"))

    def test_failed_process_creation_removes_script(self):
        with self.assertRaises(OSError):
            self.run_uninstall(mock.MagicMock(side_effect=OSError("cannot spawn")))
        self.assertFalse(list(self.base.glob("dafeiyu-uninstall-*.ps1")))


if __name__ == "__main__":
    unittest.main()
