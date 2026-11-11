import importlib.util
import tempfile
import unittest
import stat
import json
import struct
import zlib
import zipfile
from pathlib import Path
from unittest import mock
from paths import initialize_layout

_SPEC = importlib.util.spec_from_file_location(
    "build_script", Path(__file__).resolve().parents[1] / "build" / "build.py")
build = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build)


class BuildTest(unittest.TestCase):
    def test_sfx_config_text(self):
        text = build.sfx_config_text()
        self.assertTrue(text.startswith(";!@Install@!UTF-8!"))
        self.assertIn('Title="大肥鱼 QQ 助手"', text)
        self.assertIn(r'RunProgram="runtime\\python\\pythonw.exe app\\main.py"', text)
        self.assertTrue(text.rstrip().endswith(";!@InstallEnd@!"))

    def test_clean_removes_db_sidecar_files(self):
        """*.db-wal / *.db-shm 留着预热期的数据，删主库不删它们等于没清。"""
        with tempfile.TemporaryDirectory() as d:
            stage = Path(d)
            data = stage / "astrbot" / "data"
            data.mkdir(parents=True)
            for name in ("data_v4.db", "data_v4.db-wal", "data_v4.db-shm", "cmd_config.json"):
                (data / name).write_text("{}", encoding="utf-8")
            build.clean(stage, [])
            self.assertEqual(list(data.iterdir()), [])

    def test_scan_for_secrets_flags_key(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a").mkdir()
            (root / "a" / "conf.json").write_text('{"key": "sk-build"}', encoding="utf-8")
            (root / "clean.json").write_text('{"key": ""}', encoding="utf-8")
            (root / "note.txt").write_text("sk-build", encoding="utf-8")  # 只扫 json
            self.assertEqual(build.scan_for_secrets(root, ["sk-build"]), [root / "a" / "conf.json"])

    def test_separated_clean_keeps_plugin_assets(self):
        with tempfile.TemporaryDirectory() as d:
            stage = Path(d)
            layout = initialize_layout(stage)
            plugin = layout.astrbot_data / "plugins" / "test" / "main.py"
            plugin.parent.mkdir(parents=True)
            plugin.write_text("# plugin")
            meme = layout.astrbot_data / "plugin_data/meme_manager/packs/downloaded/picture.gif"
            meme.parent.mkdir(parents=True)
            meme.write_bytes(b"unlicensed fixture")
            prewarm_id = layout.astrbot_data / "plugin_data/astrbot_plugin_proactive_chat/.telemetry_id"
            prewarm_id.parent.mkdir(parents=True)
            prewarm_id.write_text("build-only-id")
            meme_config = layout.astrbot_data / "config/meme_manager_config.json"
            meme_config.parent.mkdir(parents=True)
            meme_config.write_text('{"community":{"github_accelerator_url":"https://old.example/"}}', "utf-8-sig")
            for target in (layout.astrbot_data / "data_v4.db", layout.astrbot_data / "data_v4.db-wal",
                           layout.astrbot_data / "cmd_config.json", layout.state_file, layout.info_file):
                target.write_text("build-secret")
            build.clean(stage, ["build-secret"])
            self.assertTrue(plugin.is_file())
            self.assertFalse(meme.exists())
            self.assertFalse(prewarm_id.exists())
            self.assertEqual(json.loads(meme_config.read_text("utf-8"))["community"]["github_accelerator_url"], "")
            self.assertFalse(layout.state_file.exists())
            self.assertFalse(layout.info_file.exists())
            self.assertFalse((layout.astrbot_data / "data_v4.db-wal").exists())

    def test_unzip_strips_top_directory(self):
        with tempfile.TemporaryDirectory() as d:
            src, dest = Path(d) / "input.zip", Path(d) / "out"
            with zipfile.ZipFile(src, "w") as z:
                z.writestr("release/a.txt", "a")
                z.writestr("release/dir/b.txt", "b")
            build.unzip(src, dest)
            self.assertEqual((dest / "a.txt").read_text(), "a")
            self.assertEqual((dest / "dir/b.txt").read_text(), "b")

    def test_unzip_rejects_paths_before_writing_anything(self):
        for name in ("../escape.txt", "top/../../escape.txt", "C:/escape.txt", "/escape.txt",
                     "top\\..\\escape.txt", "top/file:stream", "top/evil."):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                src, dest = Path(d) / "input.zip", Path(d) / "out"
                with zipfile.ZipFile(src, "w") as z:
                    z.writestr("top/good.txt", "good")
                    z.writestr(name, "bad")
                with self.assertRaises(ValueError):
                    build.unzip(src, dest)
                self.assertFalse(dest.exists())

    def test_unzip_rejects_symbolic_links(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "input.zip"
            info = zipfile.ZipInfo("top/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(src, "w") as z:
                z.writestr(info, "../../outside")
            with self.assertRaises(ValueError):
                build.unzip(src, Path(d) / "out")

    def test_assemble_separates_program_and_seed_data(self):
        with tempfile.TemporaryDirectory() as d:
            root, stage = Path(d) / "source", Path(d) / "stage"
            (root / "vendor/dafeiyu-config-pack/persona").mkdir(parents=True)
            (root / "vendor/dafeiyu-config-pack/persona/default.md").write_text("persona")
            (root / "app").mkdir()
            (root / "app/main.py").write_text("# main")
            for name in build.LEGAL_FILES:
                if name == "LICENSE_SCOPE.md":
                    name = "docs/许可说明.md"
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text("notice")

            def fake_python(dl, dest):
                dest.mkdir(parents=True)
                (dest / "python.exe").write_bytes(b"test only")

            def fake_unzip(src, dest):
                dest.mkdir(parents=True, exist_ok=True)

            with mock.patch.object(build, "ROOT", root), mock.patch.object(build, "run"), \
                 mock.patch.object(build, "stage_python", side_effect=fake_python), \
                 mock.patch.object(build, "unzip", side_effect=fake_unzip):
                build.assemble(stage, Path(d) / "dl")
            self.assertTrue((stage / "layout.json").is_file())
            self.assertTrue((stage / "program/runtime/python/python.exe").is_file())
            self.assertTrue((stage / "program/app/main.py").is_file())
            self.assertTrue((stage / "program/pack/persona/default.md").is_file())
            self.assertTrue((stage / "userdata/pack/persona/default.md").is_file())
            self.assertFalse((stage / "runtime").exists())
            for name in build.LEGAL_FILES:
                self.assertEqual((stage / name).read_text(), "notice")

    def test_package_copies_modern_program_to_bootstrap(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            stage, dl, work = base / "stage", base / "dl", base / "work"
            layout = initialize_layout(stage)
            for folder, name in ((layout.runtime, "pythonw.exe"), (layout.app, "main.py"),
                                 (layout.pack_defaults, "manifest.json")):
                folder.mkdir(parents=True)
                (folder / name).write_bytes(b"fixture")
            for name in build.LEGAL_FILES:
                (stage / name).write_text("notice")
            (layout.program / "licenses").mkdir()
            (layout.program / "licenses/runtime.txt").write_text("runtime license")
            dl.mkdir()
            work.mkdir()
            (dl / "7zr.exe").write_bytes(b"fixture")

            def fake_run(argv):
                if argv[1] == "a":
                    Path(argv[2]).write_bytes(b"archive fixture")
                else:
                    (work / "7zSD.sfx").write_bytes(b"sfx fixture")

            with mock.patch.object(build, "WORK", work), mock.patch.object(build, "run", side_effect=fake_run), \
                 mock.patch.object(build, "apply_sfx_manifest") as manifest:
                exe = build.package(stage, dl, base / "out")
            manifest.assert_called_once_with(work / "7zSD.sfx")
            self.assertTrue(exe.is_file())
            self.assertTrue((work / "boot/runtime/python/pythonw.exe").is_file())
            self.assertTrue((work / "boot/app/main.py").is_file())
            self.assertTrue((work / "boot/pack/manifest.json").is_file())
            self.assertFalse((work / "boot/program").exists())
            for name in build.LEGAL_FILES:
                self.assertEqual((work / "boot" / name).read_text(), "notice")
            self.assertEqual((work / "boot/licenses/runtime.txt").read_text(), "runtime license")

    def test_resume_reuses_dependencies_and_retries_failed_prewarm(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "work"
            stage = work / "stage"
            initialize_layout(stage)
            report = {"inputs": [{"file": "runtime", "sha256": "same"}]}
            with mock.patch.object(build, "WORK", work), \
                 mock.patch.object(build, "copy_runtime_licenses"), \
                 mock.patch.object(build, "copy_legal_files"), \
                 mock.patch.object(build.shutil, "copytree"), \
                 mock.patch.object(build, "prepare_sources") as prepare, \
                 mock.patch.object(build, "install_requirements") as install, \
                 mock.patch.object(build, "prewarm", return_value=[]) as prewarm, \
                 mock.patch.object(build, "write_dependency_manifest"), \
                 mock.patch.object(build, "clean") as clean, \
                 mock.patch.object(build, "package", return_value=Path(d) / "app.exe") as package:
                build._checkpoint(report, "assembled")
                build.build_stages(stage, work / "dl", Path(d) / "out", report, resume=True)
                prepare.assert_not_called()
                install.assert_not_called()
                prewarm.assert_called_once()
                clean.assert_called_once()
                package.assert_called_once()
                self.assertEqual(json.loads((work / "build-progress.json").read_text())["phase"], "clean")

    def test_resume_rejects_changed_inputs_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "work"
            stage = work / "stage"
            initialize_layout(stage)
            report = {"inputs": [{"file": "runtime", "sha256": "before"}]}
            with mock.patch.object(build, "WORK", work), mock.patch.object(build, "remove_work_tree") as remove, \
                 mock.patch.object(build, "prepare_sources") as prepare:
                build._checkpoint(report, "sources")
                report["inputs"][0]["sha256"] = "different"
                with self.assertRaisesRegex(ValueError, "已变化"):
                    build.build_stages(stage, work / "dl", Path(d) / "out", report, resume=True)
                remove.assert_not_called()
                prepare.assert_not_called()

    def test_missing_legal_file_prevents_packaging_before_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            stage, work = Path(d) / "stage", Path(d) / "work"
            initialize_layout(stage)
            boot = work / "boot"
            boot.mkdir(parents=True)
            (boot / "previous.txt").write_text("previous build")
            with mock.patch.object(build, "WORK", work), mock.patch.object(build, "run") as run:
                with self.assertRaisesRegex(ValueError, "许可"):
                    build.package(stage, Path(d) / "dl", Path(d) / "out")
                run.assert_not_called()
            self.assertEqual((boot / "previous.txt").read_text(), "previous build")

    def test_cleanup_refuses_workspace_itself_or_outside_path(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "work"
            work.mkdir()
            outside = Path(d) / "personal"
            outside.mkdir()
            for target in (work, outside, work / "../personal"):
                with self.assertRaises(ValueError):
                    build.remove_work_tree(target, work)
            self.assertTrue(outside.is_dir())

    def inputs(self, base):
        dl, downloads = base / "dl", base / "downloads"
        dl.mkdir()
        downloads.mkdir()
        for parent, name, files in (
            (dl, "python.zip", ["python.exe", "pythonw.exe", "python312.dll", "python312._pth", "python312.zip", "LICENSE.txt"]),
            (downloads, "astrbot-src.zip", ["astrbot/main.py", "astrbot/requirements.txt", "astrbot/LICENSE"]),
            (downloads, "astrbot.zip", ["dist/index.html"]),
            (downloads, "napcat-node.zip", ["node.exe", "index.js"]),
        ):
            with zipfile.ZipFile(parent / name, "w") as archive:
                for file in files:
                    archive.writestr(file, "fixture")
        pe = bytearray(68)
        pe[:2] = b"MZ"
        struct.pack_into("<I", pe, 60, 64)
        pe[64:] = b"PE\0\0"
        (dl / "7zr.exe").write_bytes(pe)
        header = bytes(20)
        (dl / "lzma.7z").write_bytes(b"7z\xbc\xaf\x27\x1c\0\x04" + struct.pack("<I", zlib.crc32(header)) + header)
        (dl / "get-pip.py").write_text("# test fixture\nprint('pip')\n")
        return dl, downloads

    def test_preflight_reports_all_seven_missing_inputs(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(build, "DOWNLOADS", Path(d) / "downloads"):
            result = build.inspect_inputs(Path(d) / "dl")
        self.assertFalse(result["ready"])
        self.assertEqual(len(result["inputs"]), 7)
        self.assertEqual({row["status"] for row in result["inputs"]}, {"missing"})

    def test_preflight_records_hash_without_claiming_publisher_verification(self):
        with tempfile.TemporaryDirectory() as d:
            dl, downloads = self.inputs(Path(d))
            with mock.patch.object(build, "DOWNLOADS", downloads):
                report = build.inspect_inputs(dl)
            self.assertTrue(report["ready"])
            self.assertTrue(all(len(row["sha256"]) == 64 for row in report["inputs"]))
            self.assertIn("not publisher verification", report["verification"])

    def test_preflight_rejects_html_fake_executable_and_zip_missing_content(self):
        with tempfile.TemporaryDirectory() as d:
            dl, downloads = self.inputs(Path(d))
            (dl / "get-pip.py").write_text("<html>error</html>")
            (dl / "7zr.exe").write_text("error page")
            with zipfile.ZipFile(downloads / "astrbot.zip", "w") as archive:
                archive.writestr("wrong.txt", "not a dashboard")
            with mock.patch.object(build, "DOWNLOADS", downloads):
                report = build.inspect_inputs(dl)
            bad = {row["file"] for row in report["inputs"] if row["status"] == "invalid"}
            self.assertEqual(bad, {"get-pip.py", "7zr.exe", "astrbot.zip"})

    def test_check_inputs_is_offline_and_keeps_old_stage(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "work"
            stage = work / "stage"
            stage.mkdir(parents=True)
            (stage / "previous.txt").write_text("old build")
            with mock.patch.object(build, "WORK", work), \
                 mock.patch.object(build, "DOWNLOADS", Path(d) / "downloads"), \
                 mock.patch.object(build.sys, "argv", ["build.py", "--check-inputs"]), \
                 mock.patch.object(build, "download") as download, mock.patch.object(build, "assemble") as assemble:
                with self.assertRaises(SystemExit):
                    build.main()
                download.assert_not_called()
                assemble.assert_not_called()
            self.assertEqual((stage / "previous.txt").read_text(), "old build")
            self.assertEqual(len(json.loads((work / "input-manifest.json").read_text("utf-8"))["inputs"]), 7)

    def test_prewarm_uses_policy_runner_without_voice_request(self):
        import services
        with tempfile.TemporaryDirectory() as d:
            stage, work = Path(d) / "stage", Path(d) / "work"
            layout = initialize_layout(stage)
            captured = {}

            def fake_run(argv):
                captured["argv"] = argv
                answers = Path(argv[argv.index("--answers") + 1])
                captured["answers"] = __import__("json").loads(answers.read_text(encoding="utf-8"))
                result = Path(argv[argv.index("--result-json") + 1])
                result.write_text('{"fatal":null,"results":[{"name":"voice","ok":true}]}')

            with mock.patch.object(build, "WORK", work), mock.patch.object(build, "run", side_effect=fake_run), \
                 mock.patch.object(services, "start_astrbot") as start, \
                 mock.patch.object(services, "stop") as stop, \
                 mock.patch.object(services, "wait_http", return_value=True):
                build.prewarm(stage)
            start.assert_called_once()
            stop.assert_called_once()
            self.assertEqual(captured["argv"][3], layout.app / "import_runner.py")
            self.assertIn("--skip-memes", captured["argv"])
            self.assertEqual(captured["answers"]["voice"], "3")
            self.assertEqual(captured["answers"]["memory"], "0")
            self.assertIs(captured["answers"]["test_voice"], False)
            self.assertFalse((work / "import/s").exists())


if __name__ == "__main__":
    unittest.main()
