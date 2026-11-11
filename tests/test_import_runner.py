import importlib.util
import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import import_runner

TOOL = Path(__file__).resolve().parent.parent / "vendor/dafeiyu-config-pack/tools/import_dafeiyu.py"


class PolicyTest(unittest.TestCase):
    def test_build_skip_omits_only_meme_downloads_and_keeps_following_steps(self):
        source = '''
def main():
    step("before")
    step("下载表情包（测试）")
    if "meme_manager" in installed:
        download()
    else:
        fail()
    step("after")
'''
        calls = []
        namespace = {"step": calls.append, "say": calls.append}
        exec(compile(import_runner.omit_build_meme_downloads(ast.parse(source)), "fixture", "exec"), namespace)
        namespace["main"]()
        self.assertEqual(calls[0], "before")
        self.assertIn("不下载", calls[1])
        self.assertEqual(calls[-1], "after")
        # The actual pinned vendor is accepted without changing its bytes.
        original = TOOL.read_bytes()
        import_runner.omit_build_meme_downloads(ast.parse(original.decode("utf-8-sig")))
        self.assertEqual(TOOL.read_bytes(), original)

    def test_build_skip_refuses_unrecognized_vendor_structure(self):
        with self.assertRaises(ValueError):
            import_runner.omit_build_meme_downloads(ast.parse('def main():\n    pass'))

    def setUp(self):
        spec = importlib.util.spec_from_file_location("vendor_fixture", TOOL)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.original_test = mock.Mock(return_value=(True, "ok"))
        self.module.test_provider = self.original_test

    def test_import_never_generates_voice_sample_even_when_enabled(self):
        finish, skipped = import_runner.configure(self.module, {"voice": "3", "memory": "2"})
        self.assertEqual(self.module.GH_ACCELERATORS, [""])
        pack = json.loads((Path(self.module.PACK) / "settings/pack.json").read_text("utf-8-sig"))
        voice_id = pack["voice"]["doubao"]["id"]
        self.assertTrue(self.module.test_provider(mock.Mock(), voice_id)[0])
        self.original_test.assert_not_called()
        self.assertEqual(skipped, [voice_id])
        self.module.test_provider(mock.Mock(), pack["memory"]["siliconflow"]["id"])
        self.original_test.assert_called_once()

    def test_off_disables_previously_installed_plugins_and_embedding_provider(self):
        finish, _ = import_runner.configure(self.module, {"voice": "0", "memory": "0"})
        api = self.module.Api("http://127.0.0.1")
        api.call = mock.Mock(side_effect=lambda method, path, *args: {
            "data": [{"name": "astrbot_plugin_dafeiyu_sing"}, {"name": "astrbot_plugin_livingmemory"}]
        } if path == "/plugins" else {"status": "ok"})
        with mock.patch.object(self.module, "provider_config", return_value={"id": "embedding", "enable": True}), \
             mock.patch.object(self.module, "upsert_provider", return_value=True) as upsert:
            finish()
        api.call.assert_any_call("PATCH", "/plugins/enabled", {"plugin_id": "astrbot_plugin_dafeiyu_sing", "enabled": False})
        api.call.assert_any_call("PATCH", "/plugins/enabled", {"plugin_id": "astrbot_plugin_livingmemory", "enabled": False})
        self.assertFalse(upsert.call_args.args[1]["enable"])

    def test_enabling_voice_reenables_sing_but_does_not_override_failed_memory(self):
        finish, _ = import_runner.configure(self.module, {"voice": "3", "memory": "2"})
        self.module.RESULTS.append(("语音", True))
        api = self.module.Api("http://127.0.0.1")
        api.call = mock.Mock(side_effect=lambda method, path, *args: {
            "data": [{"name": "astrbot_plugin_dafeiyu_sing"}, {"name": "astrbot_plugin_livingmemory"}]
        } if path == "/plugins" else {})
        finish()
        patches = [call.args[2] for call in api.call.call_args_list if call.args[0] == "PATCH"]
        self.assertEqual(patches, [{"plugin_id": "astrbot_plugin_dafeiyu_sing", "enabled": True}])

    def test_invalid_answers_produce_failure_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            answers, result = Path(tmp) / "a.json", Path(tmp) / "result.json"
            answers.write_text('{"voice":"1","memory":"0"}')
            self.assertEqual(import_runner.run(TOOL, answers, result), 1)
            self.assertIn("ValueError", json.loads(result.read_text("utf-8"))["fatal"])


if __name__ == "__main__":
    unittest.main()
