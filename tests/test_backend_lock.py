import io
import json
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend_lock import BackendLock, instance_url


def _compete(root, home, ready, go, release, outcomes):
    ready.put("ready")
    if not go.wait(10):
        outcomes.put("timeout")
        return
    lease = BackendLock(Path(root), Path(home))
    acquired = lease.try_acquire()
    outcomes.put(acquired)
    if acquired:
        release.wait(10)
        lease.release()


def _exit_without_release(root, home, ready):
    lease = BackendLock(Path(root), Path(home))
    if not lease.try_acquire():
        raise RuntimeError("unexpected lock collision")
    # Pipe.send 同步送达，随后正常进程退出模拟未执行 finally 的崩溃。
    ready.send(True)
    ready.close()
    os._exit(0)


class BackendLockTest(unittest.TestCase):
    def test_different_modes_share_same_install_lock(self):
        with tempfile.TemporaryDirectory() as d:
            root, home = Path(d) / "install", Path(d) / "home"
            first, second = BackendLock(root, home), BackendLock(root / ".", home)
            self.assertTrue(first.try_acquire())
            try:
                self.assertFalse(second.try_acquire())
                first.publish(12345, "one-token")
                info = json.loads(second.metadata.read_text("utf-8"))
                self.assertEqual((info["port"], info["token"]), (12345, "one-token"))
            finally:
                first.release()
            self.assertTrue(second.try_acquire())
            second.release()

    def test_independent_processes_only_one_wins_simultaneous_start(self):
        ctx = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as d:
            ready, results = ctx.Queue(), ctx.Queue()
            go, release = ctx.Event(), ctx.Event()
            workers = [ctx.Process(target=_compete, args=(str(Path(d) / "install"), str(Path(d) / "home"),
                                                         ready, go, release, results)) for _ in range(2)]
            for process in workers:
                process.start()
            self.assertEqual([ready.get(timeout=10) for _ in workers], ["ready", "ready"])
            go.set()
            outcomes = [results.get(timeout=10) for _ in workers]
            release.set()
            for process in workers:
                process.join(10)
                self.assertEqual(process.exitcode, 0)
                process.close()
            self.assertEqual(sorted(outcomes), [False, True])
            ready.close()
            results.close()

    def test_process_exit_releases_os_lock_without_clean_metadata(self):
        ctx = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as d:
            root, home = Path(d) / "install", Path(d) / "home"
            receiver, sender = ctx.Pipe(duplex=False)
            process = ctx.Process(target=_exit_without_release, args=(str(root), str(home), sender))
            process.start()
            sender.close()
            self.assertTrue(receiver.poll(10))
            self.assertTrue(receiver.recv())
            process.join(10)
            self.assertEqual(process.exitcode, 0)
            lease = BackendLock(root, home)
            self.assertTrue(lease.try_acquire())
            lease.release()
            receiver.close()
            process.close()

    def test_existing_url_preserves_existing_token(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "metadata.json"
            path.write_text(json.dumps({"port": 12345, "token": "retained-token"}), encoding="utf-8")
            response = mock.MagicMock()
            opener = mock.Mock(return_value=response)
            self.assertEqual(instance_url(path, opener), "http://127.0.0.1:12345/?token=retained-token")
            request = opener.call_args.args[0]
            self.assertEqual(request.get_header("X-token"), "retained-token")

    def test_stale_metadata_is_not_a_live_instance(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "metadata.json"
            path.write_text(json.dumps({"port": 12345, "token": "old"}), encoding="utf-8")
            self.assertIsNone(instance_url(path, mock.Mock(side_effect=OSError("closed"))))


if __name__ == "__main__":
    unittest.main()
