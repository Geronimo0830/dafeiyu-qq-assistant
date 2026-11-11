import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import main as entry
from store import State, remember_install


def args(status=False, root=None):
    return argparse.Namespace(status=status, root=root, no_window=True)


class ResolveModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.root = Path(self.tmp.name) / "DaFeiYu"
        self.root.mkdir()
        self.complete_files = mock.patch.object(entry.installer, "extracted_ok", return_value=True)
        self.complete_files.start()

    def tearDown(self):
        self.complete_files.stop()
        self.tmp.cleanup()

    def install(self):
        state = State.load(self.root)
        state.data.update(done=[step.key for step in entry.installer.default_steps()],
                          keys_ok=True, profile={"name": "fish"})
        state.save()
        remember_install(self.root, self.home)

    def test_fresh_machine_gets_the_wizard(self):
        self.assertEqual(entry.resolve_mode(args(), self.home), ("install", None))

    def test_installed_machine_gets_the_status_page(self):
        """双击一键包时已经装过，就该直接看到状态页，而不是又让人选一次安装位置。"""
        self.install()
        self.assertEqual(entry.resolve_mode(args(), self.home), ("status", self.root))

    def test_shortcut_always_gets_the_status_page(self):
        self.install()
        self.assertEqual(entry.resolve_mode(args(status=True, root=str(self.root)), self.home),
                         ("status", self.root))

    def test_install_dir_deleted_falls_back_to_the_wizard(self):
        remember_install(self.root, self.home)  # 记着，但目录里的 state.json 已经没了
        self.assertEqual(entry.resolve_mode(args(), self.home), ("install", None))

    def test_explicit_root_wins(self):
        self.install()
        other = Path(self.tmp.name) / "其他"
        other.mkdir()
        (other / "state.json").write_text("{}", encoding="utf-8")
        self.assertEqual(entry.resolve_mode(args(status=True, root=str(other)), self.home), ("install", other))

    def test_interrupted_install_resumes_even_with_status_flag(self):
        state = State.load(self.root)
        state.data.update(done=["extract", "ports"], keys_ok=True)
        state.save()
        remember_install(self.root, self.home)
        self.assertEqual(entry.resolve_mode(args(), self.home), ("install", self.root))
        self.assertEqual(entry.resolve_mode(args(status=True, root=str(self.root)), self.home),
                         ("install", self.root))

    def test_missing_saved_inputs_do_not_count_as_complete(self):
        self.install()
        state = State.load(self.root)
        state.data.pop("profile")
        state.save()
        self.assertEqual(entry.resolve_mode(args(), self.home), ("install", self.root))

    def test_missing_program_files_resumes_repair(self):
        self.install()
        with mock.patch.object(entry.installer, "extracted_ok", return_value=False):
            self.assertEqual(entry.resolve_mode(args(), self.home), ("install", self.root))

    def test_new_layout_resolves_userdata_state_without_mutation(self):
        from paths import initialize_layout
        initialize_layout(self.root)
        self.install()
        before = {str(path.relative_to(self.root)): path.read_bytes()
                  for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(entry.resolve_mode(args(), self.home), ("status", self.root))
        after = {str(path.relative_to(self.root)): path.read_bytes()
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)


class LockTest(unittest.TestCase):
    def test_install_and_status_share_window_profile(self):
        home = Path("home")
        self.assertEqual(entry.window_files("install", home), entry.window_files("status", home))


class BackendLifetimeTest(unittest.TestCase):
    def test_only_new_status_backend_starts_services(self):
        app = mock.Mock(mode="status")
        entry.start_initial_services(app)
        app.handle_start.assert_called_once_with({})
        app.mode = "install"
        app.handle_start.reset_mock()
        entry.start_initial_services(app)
        app.handle_start.assert_not_called()

    def test_running_owned_service_keeps_backend_alive(self):
        app = mock.Mock(installer=None, _starter=None, state=mock.sentinel.state)
        with mock.patch.object(entry.services, "managed_services_running", return_value=True, create=True) as running:
            self.assertTrue(entry.backend_busy(app))
        running.assert_called_once_with(app.state)

    def test_service_start_worker_keeps_backend_alive(self):
        app = mock.Mock(installer=None, state=None)
        app._starter.progress.return_value = {"running": True, "waiting": None}
        self.assertTrue(entry.backend_busy(app))

    def test_waiting_for_input_without_services_can_exit(self):
        app = mock.Mock(_starter=None, state=None)
        app.installer.progress.return_value = {"running": True, "waiting": "keys"}
        self.assertFalse(entry.backend_busy(app))

    def test_idle_without_services_can_exit(self):
        app = mock.Mock(installer=None, _starter=None, state=mock.sentinel.state)
        with mock.patch.object(entry.services, "managed_services_running", return_value=False, create=True):
            self.assertFalse(entry.backend_busy(app))


if __name__ == "__main__":
    unittest.main()
