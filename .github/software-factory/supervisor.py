"""Bounded Factory Agent runner. Raw output stays local; logs contain file activity only."""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

HEARTBEAT_SECONDS = 60
KILL_GRACE_SECONDS = 15
PHASES = {"implement": ("implement", None), "retro": ("retro", None),
          **{f"{phase}-{axis}": (phase, axis) for phase in ("review", "final")
             for axis in ("standards", "spec")}}


def emit(prefix, value):
    # A full or closed log pipe must never prevent deadline/cancellation cleanup.
    try:
        os.write(sys.stdout.fileno(), f"{prefix} {json.dumps(value, sort_keys=True)}\n".encode())
    except OSError:
        pass


def send_group(process, sig):
    try:
        os.killpg(process.pid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def cleanup(process):
    # Keep the PGID even after poll() reaps the leader: descendants may ignore TERM.
    if send_group(process, signal.SIGTERM):
        deadline = time.monotonic() + KILL_GRACE_SECONDS
        while time.monotonic() < deadline:
            process.poll()
            if not send_group(process, 0):
                break
            time.sleep(min(.05, max(0, deadline - time.monotonic())))
        send_group(process, signal.SIGKILL)
    process.wait()


def main(args):
    try:
        result_file, summary, phase, budget, separator, *command = args
        budget = float(budget)
        if phase not in PHASES or separator != "--" or not command or not math.isfinite(budget) or budget <= 0:
            raise ValueError
    except ValueError:
        print("::error::invalid-supervisor-input", file=sys.stderr)
        return 2

    phase_name, axis = PHASES[phase]
    stdout_blocking = os.get_blocking(sys.stdout.fileno())
    os.set_blocking(sys.stdout.fileno(), False)
    clock = time.monotonic()
    cancelled = 0

    def cancel(sig, _frame):
        nonlocal cancelled
        cancelled = cancelled or sig

    def activity():
        sizes = []
        for filename in (result_file, os.environ.get("CLAUDE_TRANSCRIPT")):
            try:
                sizes.append(Path(filename).stat().st_size if filename else 0)
            except OSError:
                sizes.append(0)
        return {"result_bytes": sizes[0], "transcript_bytes": sizes[1]}

    old_handlers = {sig: signal.signal(sig, cancel) for sig in (signal.SIGTERM, signal.SIGINT)}
    process, status = None, 125
    next_heartbeat, last_activity, observed = clock + HEARTBEAT_SECONDS, None, activity()
    try:
        with Path(result_file).open("wb") as output, Path(result_file).with_suffix(".stderr").open("wb") as errors:
            try:
                process = subprocess.Popen(command, stdout=output, stderr=errors, start_new_session=True)
            except OSError:
                status = 127
            if process:
                while True:
                    now = time.monotonic()
                    if cancelled:
                        status = 128 + cancelled
                        break
                    result = process.poll()
                    if result is not None:
                        status = result if result >= 0 else 128 - result
                        break
                    if now - clock >= budget:
                        status = 124
                        break
                    if now >= next_heartbeat:
                        try:
                            current = activity()
                            if current != observed:
                                observed, last_activity = current, time.time()
                            emit("agent-heartbeat", {
                                "phase": phase_name, "axis": axis,
                                "elapsed_seconds": round(now - clock, 2),
                                "last_activity_age_seconds": (round(max(0, time.time() - last_activity), 2)
                                                              if last_activity is not None else None), **current})
                        except Exception:
                            emit("agent-heartbeat", {"phase": phase_name, "axis": axis,
                                                     "elapsed_seconds": int(now - clock), "available": False})
                        next_heartbeat = now + HEARTBEAT_SECONDS
                    time.sleep(min(.05, max(0, clock + budget - now)))
    except Exception:
        emit("agent-supervisor", {"status": "runner-error"})
    finally:
        if process:
            cleanup(process)
        if cancelled and status != 124:
            status = 128 + cancelled
        try:
            counts = {"exit_status": status, "elapsed_seconds": int(time.monotonic() - clock), **activity()}
            line = json.dumps(counts, sort_keys=True)
            Path(summary).write_text(f"agent-summary {line}\n")
            emit("agent-summary", counts)
            if os.environ.get("GITHUB_STEP_SUMMARY"):
                with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as target:
                    target.write(f"### Factory Agent run\n\n```json\n{line}\n```\n")
        except Exception:
            emit("agent-supervisor", {"status": "summary-failed"})
        os.set_blocking(sys.stdout.fileno(), stdout_blocking)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
