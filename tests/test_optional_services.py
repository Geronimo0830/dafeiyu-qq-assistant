import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import personalize
import server
from tests.test_server import FakeChecks, PACK


class OptionalServicesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "install"
        self.boot = Path(self.tmp.name) / "boot"
        shutil.copytree(PACK, self.boot / "pack")
        FakeChecks.calls = []
        self.app = self.open_app()

    def tearDown(self):
        self.tmp.cleanup()

    def open_app(self):
        return server.App("install", root=self.root, boot=self.boot, checks_mod=FakeChecks,
                          steps_factory=lambda: [])

    def keys(self, **changes):
        result = {"owner_qq": "123456", "deepseek": "sk-chat", "siliconflow": "sf-memory",
                  "app_id": "voice-app", "token": "voice-token",
                  "features": {"voice": False, "memory": False}}
        result.update(changes)
        return result

    def test_new_install_needs_only_chat_credentials(self):
        self.assertEqual(self.app.handle_info({})["features"], {"voice": False, "memory": False})
        result = self.app.handle_keys(self.keys(siliconflow="", app_id="", token=""))
        self.assertTrue(result["ok"])
        self.assertEqual(FakeChecks.calls, [("deepseek", "sk-chat")])
        self.assertEqual(self.app.state.get_secret("doubao_token"), "")

    def test_enabling_voice_requires_consent_before_any_tts_call(self):
        result = self.app.handle_keys(self.keys(features={"voice": True, "memory": False}))
        self.assertFalse(result["ok"])
        self.assertIn("doubao", result["errors"])
        self.assertFalse(any(call[0] == "doubao" for call in FakeChecks.calls))
        self.assertFalse(self.app.handle_check({"field": "doubao", "app_id": "a", "token": "t"})["ok"])
        self.assertFalse(any(call[0] == "doubao" for call in FakeChecks.calls))

    def test_reopening_and_saving_unchanged_keys_never_tests_voice_again(self):
        self.assertTrue(self.app.handle_keys(self.keys(features={"voice": True, "memory": True},
                                                      voice_consent=True))["ok"])
        self.app = self.open_app()
        FakeChecks.calls.clear()
        result = self.app.handle_keys({"owner_qq": "123456", "features": {"voice": True, "memory": True}})
        self.assertTrue(result["ok"])
        self.assertEqual(FakeChecks.calls, [])

    def test_disabling_keeps_saved_secrets_without_checking_them(self):
        self.app.handle_keys(self.keys(features={"voice": True, "memory": True}, voice_consent=True))
        FakeChecks.calls.clear()
        self.assertTrue(self.app.handle_keys(self.keys())["ok"])
        self.assertEqual(FakeChecks.calls, [])
        self.assertEqual(self.app.state.get_secret("siliconflow"), "sf-memory")
        self.assertEqual(self.app.state.get_secret("doubao_token"), "voice-token")
        self.assertEqual(self.app.features(), {"voice": False, "memory": False})

    def test_voice_preview_requires_enabled_service_and_explicit_consent(self):
        self.assertFalse(self.app.handle_preview_voice({"voice_consent": True})["ok"])
        self.app.handle_keys(self.keys(features={"voice": True, "memory": False}, voice_consent=True))
        FakeChecks.calls.clear()
        self.assertFalse(self.app.handle_preview_voice({})["ok"])
        self.assertEqual(FakeChecks.calls, [])
        self.assertTrue(self.app.handle_preview_voice({"voice_consent": True})["ok"])
        self.assertEqual(FakeChecks.calls, [("doubao", "voice-app")])

    def test_disabled_voice_does_not_require_voice_description(self):
        profile = self.app.handle_info({})["profile"]
        profile["voice"] = ""
        self.assertTrue(self.app.handle_profile(profile)["ok"])
        self.assertTrue(self.app.state.data["profile"]["voice"])

    def test_legacy_install_preserves_configured_features(self):
        self.assertEqual(personalize.enabled_features({"keys_ok": True}), {"voice": True, "memory": True})
        self.assertEqual(personalize.enabled_features({"keys_ok": True, "features": {"voice": False}}),
                         {"voice": False, "memory": False})

    def test_disabled_answers_omit_unused_credential_files(self):
        answers, secrets = Path(self.tmp.name) / "answers.json", Path(self.tmp.name) / "secrets"
        personalize.write_answers(answers, base_url="http://127.0.0.1:6185", username="user", password="pass",
                                  owner_qq="123456", secrets_dir=secrets, sf_key="sf", app_id="app", token="token")
        data = json.loads(answers.read_text("utf-8"))
        self.assertEqual((data["voice"], data["memory"], data["test_voice"]), ("0", "0", False))
        self.assertEqual({p.name for p in secrets.iterdir()}, {"password.txt"})
        self.assertNotIn("volc_app_id", data)

    def test_returning_to_keys_while_waiting_profile_marks_reapply(self):
        self.app.handle_keys(self.keys())
        self.app.state.mark_done("configs")
        with mock.patch.object(self.app.installer, "progress", return_value={
                "running": True, "finished": False, "waiting": "profile", "steps": []}):
            self.assertTrue(self.app.handle_keys(self.keys(deepseek="sk-updated"))["ok"])
        self.assertTrue(self.app.state.data["settings_pending"])
        self.assertEqual(self.app.state.get_secret("deepseek"), "sk-updated")

    def test_changes_are_rejected_while_import_is_reading_settings(self):
        self.app.handle_keys(self.keys())
        self.app.handle_profile(self.app.handle_info({})["profile"])
        FakeChecks.calls.clear()
        with mock.patch.object(self.app.installer, "progress", return_value={
                "running": True, "finished": False, "waiting": None,
                "steps": [{"key": "import", "status": "doing"}]}):
            self.assertEqual(self.app.handle_keys(self.keys())["code"], "busy")
            self.assertEqual(self.app.handle_profile({})["code"], "busy")
        self.assertEqual(FakeChecks.calls, [])

    def test_status_ignores_reused_process_id(self):
        self.app.state.data.update(pids={"astrbot": 123}, processes={"astrbot": {"created": 1, "exe": "old"}})
        self.app.state.save()
        with mock.patch.object(server.services, "is_running", return_value=True), \
                mock.patch.object(server.services, "process_identity", return_value={"created": 2, "exe": "new"}):
            self.assertFalse(self.app.handle_status({})["astrbot"])

    def test_pending_settings_are_applied_before_starting_services(self):
        self.app.state.data["settings_pending"] = True
        with mock.patch.object(self.app, "handle_apply", return_value={"ok": True}) as apply:
            self.assertTrue(self.app.handle_start({})["ok"])
        apply.assert_called_once_with({})
        self.assertIsNone(self.app._starter)

    def test_stopped_status_does_not_query_an_unowned_service(self):
        with mock.patch.object(self.app, "login_status") as login:
            self.assertEqual(self.app.handle_status({})["login"], "offline")
        login.assert_not_called()

    def test_apply_discards_old_start_error_before_retrying_configuration(self):
        self.app._starter = mock.Mock()
        self.app._starter.progress.return_value = {"running": False, "steps": [{"status": "error"}]}
        self.app._web = mock.sentinel.old_connection
        with mock.patch.object(server.services, "stop_all"), mock.patch.object(self.app.installer, "redo") as redo:
            self.assertTrue(self.app.handle_apply({})["ok"])
        self.assertIsNone(self.app._starter)
        self.assertIsNone(self.app._web)
        redo.assert_called_once()

    def test_status_refresh_restarts_after_clearing_stale_login(self):
        self.app._web = mock.Mock(last_error="当前账号已登录")
        self.app.state.data["qq"] = "123456"
        with mock.patch.object(server.services, "stop") as stop, \
                mock.patch.object(self.app, "handle_start", return_value={"ok": True}) as start:
            self.assertTrue(self.app.handle_refresh_qr({})["ok"])
        stop.assert_called_once_with(self.app.state, "napcat")
        start.assert_called_once_with({})
        self.assertNotIn("qq", self.app.state.data)

    def test_duplicate_submit_does_not_run_second_provider_check(self):
        entered, release = threading.Event(), threading.Event()
        responses = []

        def slow_check(key):
            entered.set()
            if not release.wait(3):
                raise TimeoutError("test barrier")
            return True, "ok"

        with mock.patch.object(FakeChecks, "check_deepseek", side_effect=slow_check) as check:
            worker = threading.Thread(target=lambda: responses.append(self.app.handle_keys(self.keys())))
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(self.app.handle_keys(self.keys())["code"], "busy")
            finally:
                release.set()
                worker.join(3)
        check.assert_called_once()
        self.assertTrue(responses[0]["ok"])


if __name__ == "__main__":
    unittest.main()
