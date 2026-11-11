import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from store import State, StateConflictError, protect, redact, unprotect


def _save_process(root, field, ready, go, results, conflict=False):
    try:
        state = State.load(Path(root))
        state.data.setdefault("nested", {})["shared" if conflict else field] = field
        ready.put(field)
        if not go.wait(10):
            raise TimeoutError("test start barrier")
        state.save()
        results.put((field, "ok"))
    except Exception as error:
        results.put((field, type(error).__name__))


class StoreTest(unittest.TestCase):
    def test_dpapi_roundtrip(self):
        blob = protect("sk-abc")
        self.assertNotIn("sk-abc", blob)
        self.assertEqual(unprotect(blob), "sk-abc")

    def test_state_persists_and_hides_secrets(self):
        with tempfile.TemporaryDirectory() as d:
            s = State.load(Path(d))
            s.set_secret("deepseek", "sk-secret-123")
            s.save()
            raw = (Path(d) / "state.json").read_text(encoding="utf-8")
            self.assertNotIn("sk-secret-123", raw)
            self.assertEqual(State.load(Path(d)).get_secret("deepseek"), "sk-secret-123")

    def test_missing_secret_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(State.load(Path(d)).get_secret("nope"), "")

    def test_mark_done(self):
        with tempfile.TemporaryDirectory() as d:
            s = State.load(Path(d))
            self.assertFalse(s.is_done("extract"))
            s.mark_done("extract")
            self.assertTrue(State.load(Path(d)).is_done("extract"))
            self.assertEqual(json.loads((Path(d) / "state.json").read_text("utf-8"))["done"], ["extract"])

    def test_reload_pids_sees_other_window(self):
        """两个向导窗口各写各的 pids，状态页必须读盘上那份，否则会显示「她下线了」。"""
        with tempfile.TemporaryDirectory() as d:
            page = State.load(Path(d))       # 状态页：启动时盘上还没有 pid
            other = State.load(Path(d))      # 另一个窗口刚起了服务
            other.data["pids"] = {"astrbot": 123, "napcat": 456}
            other.save()
            self.assertFalse(page.data.get("pids"))
            self.assertEqual(page.reload_pids(), {"astrbot": 123, "napcat": 456})

    def test_reload_pids_survives_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            s = State.load(Path(d))
            s.data["pids"] = {"astrbot": 1}
            s.save()
            (Path(d) / "state.json").unlink()
            self.assertEqual(s.reload_pids(), {})

    def test_concurrent_saves(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            states = [State.load(Path(d)) for _ in range(3)]
            errors = []

            def hammer(s, field):
                try:
                    for i in range(20):
                        s.data[field] = i
                        s.save()
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=hammer, args=(s, str(i))) for i, s in enumerate(states)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            self.assertEqual([State.load(Path(d)).data[str(i)] for i in range(3)], [19, 19, 19])

    def test_nested_removal_survives_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            first = State.load(Path(d))
            first.data["pids"] = {"astrbot": 1, "napcat": 2}
            first.save()
            stale = State.load(Path(d))
            first.data["pids"].pop("napcat")
            first.save()
            stale.data["pids"]["astrbot"] = 3
            stale.save()
            self.assertEqual(State.load(Path(d)).data["pids"], {"astrbot": 3})

    def test_conflict_is_explicit_and_does_not_overwrite_disk(self):
        with tempfile.TemporaryDirectory() as d:
            first, second = State.load(Path(d)), State.load(Path(d))
            first.data["profile"] = {"name": "first"}
            second.data["profile"] = {"name": "second"}
            first.save()
            with self.assertRaisesRegex(StateConflictError, "profile.name"):
                second.save()
            self.assertEqual(State.load(Path(d)).data["profile"], {"name": "first"})
            self.assertFalse(list(Path(d).glob("state.*.tmp")))

    def test_reload_pids_refreshes_process_identity_and_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            page, other = State.load(Path(d)), State.load(Path(d))
            other.data.update(pids={"astrbot": 42}, processes={"astrbot": {"created": 7, "exe": "python.exe"}})
            other.save()
            page.reload_pids()
            self.assertEqual(page.data["processes"], other.data["processes"])
            page.data["pids"].clear()
            page.data["processes"].clear()
            page.save()
            self.assertEqual(State.load(Path(d)).data["pids"], {})
            self.assertEqual(State.load(Path(d)).data["processes"], {})

    def _multiprocess_saves(self, conflict):
        ctx = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as d:
            ready, results, go = ctx.Queue(), ctx.Queue(), ctx.Event()
            processes = [ctx.Process(target=_save_process, args=(d, field, ready, go, results, conflict))
                         for field in ("one", "two")]
            for process in processes:
                process.start()
            self.assertEqual({ready.get(timeout=10) for _ in processes}, {"one", "two"})
            go.set()
            outcomes = [results.get(timeout=15) for _ in processes]
            for process in processes:
                process.join(10)
                self.assertEqual(process.exitcode, 0)
                process.close()
            if conflict:
                self.assertEqual(sorted(result for _, result in outcomes), ["StateConflictError", "ok"])
            else:
                self.assertEqual([result for _, result in outcomes], ["ok", "ok"])
                self.assertEqual(State.load(Path(d)).data["nested"], {"one": "one", "two": "two"})
            ready.close()
            results.close()

    def test_independent_processes_merge_disjoint_nested_updates(self):
        self._multiprocess_saves(False)

    def test_independent_processes_reject_conflicting_updates(self):
        self._multiprocess_saves(True)

    def test_separated_layout_uses_userdata_state(self):
        from paths import initialize_layout
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            initialize_layout(root)
            state = State.load(root)
            state.data["profile"] = {"name": "kept"}
            state.save()
            self.assertTrue((root / "userdata" / "state.json").exists())
            self.assertFalse((root / "state.json").exists())
            self.assertEqual(State.load(root).data["profile"], {"name": "kept"})

    def test_remember_install(self):
        from store import last_install, remember_install
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "home"
            self.assertIsNone(last_install(home))
            remember_install(Path("D:\\DaFeiYu"), home)
            self.assertEqual(last_install(home), "D:\\DaFeiYu")

    def test_redact_masks_all_secrets(self):
        out = redact("key sk-aaaa and tok-bbbb and ab", ["sk-aaaa", "tok-bbbb", "ab", ""])
        self.assertEqual(out, "key *** and *** and ab")


if __name__ == "__main__":
    unittest.main()
