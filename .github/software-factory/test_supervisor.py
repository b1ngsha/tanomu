import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

SUPERVISOR = Path(__file__).with_name("supervisor.py")
SECRET = "private-prompt-and-stderr"
# Exercise real processes with short clocks, without adding production override knobs.
ENTRY = """import importlib.util, sys
spec = importlib.util.spec_from_file_location('supervisor', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.HEARTBEAT_SECONDS = .08
module.KILL_GRACE_SECONDS = .15
sys.exit(module.main(sys.argv[2:]))
"""


class SupervisorTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.events = self.root / "events.jsonl"
        self.summary = self.root / "summary.txt"
        self.github = self.root / "github-summary"

    def start(self, source, budget="2", phase="review-standards", command=None):
        args = [sys.executable, "-I", "-c", ENTRY, str(SUPERVISOR), str(self.events),
                str(self.summary), phase, budget, "--"]
        process = subprocess.Popen(args + (command or [sys.executable, "-I", "-c", source, SECRET]),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=self.root,
                                   env={**os.environ, "GITHUB_STEP_SUMMARY": str(self.github)})
        self.addCleanup(lambda: process.poll() is None and process.kill())
        return process

    def finish(self, process, status):
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, status, stderr)
        self.assertNotIn(SECRET, stdout + stderr + self.github.read_text() + self.summary.read_text())
        self.assertEqual(stderr, "")
        summary = json.loads(self.summary.read_text().removeprefix("agent-summary "))
        self.assertEqual(summary["exit_status"], status)
        self.assertIn(self.summary.read_text().strip(), stdout)
        return stdout, summary

    def test_normal_nonzero_and_signal_exits_preserve_status_and_private_files(self):
        for code, status in (("pass", 0), ("sys.exit(7)", 7),
                             ("os.kill(os.getpid(), signal.SIGTERM)", 143)):
            with self.subTest(status=status):
                source = ("import os, signal, sys; print(sys.argv[1], flush=True); "
                          "print(sys.argv[1], file=sys.stderr, flush=True); " + code)
                self.finish(self.start(source), status)
                self.assertIn(SECRET, self.events.read_text())
                self.assertIn(SECRET, self.events.with_suffix(".stderr").read_text())

    def test_heartbeat_counts_activity_and_silence_without_echoing_fields(self):
        source = (f"import time; print({SECRET!r}, flush=True); time.sleep(.22); "
                  "print('more output', flush=True); time.sleep(.28)")
        stdout, final = self.finish(self.start(source), 0)
        beats = [json.loads(line.removeprefix("agent-heartbeat ")) for line in stdout.splitlines()
                 if line.startswith("agent-heartbeat ")]
        self.assertGreaterEqual(len(beats), 3)
        self.assertTrue(all(beat["phase"] == "review" and beat["axis"] == "standards" for beat in beats))
        self.assertTrue(any(beat["result_bytes"] > 0 for beat in beats))
        self.assertTrue(any(beat["last_activity_age_seconds"] > .08 for beat in beats))
        self.assertGreater(final["result_bytes"], 0)

    def test_silent_timeout_is_124_and_emits_heartbeat(self):
        stdout, summary = self.finish(self.start("import time; time.sleep(20)", budget=".25"), 124)
        self.assertIn('"last_activity_age_seconds": null', stdout)
        self.assertEqual(summary["result_bytes"], 0)
        self.assertEqual(summary["transcript_bytes"], 0)

    def test_isolated_control_import_ignores_modules_in_candidate_directory(self):
        (self.root / "control.py").write_text(f"raise RuntimeError({SECRET!r})")
        (self.root / "json.py").write_text(f"raise RuntimeError({SECRET!r})")
        self.finish(self.start("print('{}')"), 0)

    def test_full_log_pipe_does_not_block_timeout_or_summary(self):
        reader, writer = os.pipe()
        os.set_blocking(writer, False)
        try:
            while True:
                os.write(writer, b"x" * 4096)
        except BlockingIOError:
            pass
        args = [sys.executable, "-I", "-c", ENTRY, str(SUPERVISOR), str(self.events),
                str(self.summary), "implement", ".25", "--", sys.executable, "-I", "-c",
                "import time; time.sleep(20)"]
        process = subprocess.Popen(args, stdout=writer, stderr=subprocess.PIPE,
                                   env={**os.environ, "GITHUB_STEP_SUMMARY": str(self.github)})
        try:
            self.assertEqual(process.wait(timeout=3), 124)
            self.assertIn('"exit_status": 124', self.summary.read_text())
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=3)
            os.close(reader)
            os.close(writer)

    def test_spawn_failure_and_invalid_phase_are_sanitized(self):
        self.finish(self.start("", command=[str(self.root / SECRET)]), 127)
        process = self.start("pass", phase=SECRET)
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 2)
        self.assertNotIn(SECRET, stdout + stderr)

    def test_timeout_and_cancellation_kill_descendants_after_leader_exit(self):
        for cancel in (None, signal.SIGTERM, signal.SIGINT):
            with self.subTest(cancel=cancel):
                pidfile = self.root / "pid"
                pidfile.unlink(missing_ok=True)
                # Leader exits on TERM; its child ignores TERM and keeps the process group alive.
                child = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(20)"
                source = ("import subprocess,sys,time; from pathlib import Path; "
                          f"p=subprocess.Popen([sys.executable,'-I','-c',{child!r}]); "
                          f"Path({str(pidfile)!r}).write_text(str(p.pid)); time.sleep(20)")
                process = self.start(source, budget=".35" if cancel is None else "2")
                deadline = time.monotonic() + 2
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(pidfile.exists())
                time.sleep(.08)
                if cancel:
                    process.send_signal(cancel)
                self.finish(process, 128 + cancel if cancel else 124)
                # A killed child can remain a zombie briefly on Linux, but cannot execute.
                pid = int(pidfile.read_text())
                try:
                    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                                           capture_output=True, text=True, check=False).stdout.strip()
                    self.assertTrue(not state or state.startswith("Z"), state)
                finally:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_normal_leader_exit_also_cleans_background_children(self):
        pidfile = self.root / "background-pid"
        source = ("import subprocess,sys; from pathlib import Path; "
                  "p=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(20)']); "
                  f"Path({str(pidfile)!r}).write_text(str(p.pid))")
        self.finish(self.start(source), 0)
        state = subprocess.run(["ps", "-o", "stat=", "-p", pidfile.read_text()],
                               capture_output=True, text=True).stdout.strip()
        self.assertTrue(not state or state.startswith("Z"), state)


if __name__ == "__main__":
    unittest.main()
