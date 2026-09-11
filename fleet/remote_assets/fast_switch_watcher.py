#!/usr/bin/env python3
"""Fast idle-gap switcher, deployed and launched by fleet/remote.py.

Polls every 1s for up to a configurable number of seconds, watching for the
moment fleet's live-recommended target differs from the currently-warm model
AND the daemon goes idle, then executes the switch immediately. fleet
launches this in the background (self-locking) whenever a tick decides a
switch is warranted but the host is currently busy, so a narrow idle gap that
opens and closes between fleet's own ~60s ticks doesn't get missed - exactly
that gap was missed 8 consecutive ticks in a row on the real host on
2026-09-11 before this existed (see README).

fleet's own process can't call back into this once launched, so it re-reads
its live recommendation from a small JSON state file that fleet rewrites
over SSH every tick the recommendation stands or changes, rather than take a
fixed target - this self-corrects if the recommendation changes mid-wait.

Standalone stdlib script: fleet copies this file verbatim to the remote host
and runs it there with the host's own python3, so it must not import the
fleet package or any third-party dependency.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
WIDGET_DIR = HOME / ".darkbloom-widget"
TARGET_STATE_PATH = WIDGET_DIR / "fleet-target.json"
DAEMON_STATE_PATH = HOME / ".darkbloom" / "daemon-state.json"
DARKBLOOM_BIN = HOME / ".darkbloom" / "bin" / "darkbloom"
LOG = WIDGET_DIR / "fast_switch.log"
LOCK_FILE = Path("/tmp/darkbloom-fast-switch.lock")
POLL_SECONDS = 1
DEFAULT_MAX_SECONDS = 55


def acquire_lock_or_exit():
    """macOS has no flock CLI, so lock via a PID file checked with signal 0."""
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            os.kill(pid, 0)
            sys.exit(0)  # another instance is alive, nothing to do
        except (ValueError, ProcessLookupError, PermissionError):
            pass  # stale or unreadable lock, take it over
    LOCK_FILE.write_text(str(os.getpid()))


def log(msg):
    line = "%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), msg)
    with LOG.open("a") as f:
        f.write(line)
    print(line, end="")


def read_target_state():
    """Returns (target, valid_targets, max_seconds) from the state file fleet
    writes over SSH. target is None if the file is missing/unreadable or
    names a model outside valid_targets - the same defensive check the
    original manager-observer version applied to its own hardcoded set."""
    try:
        state = json.loads(TARGET_STATE_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return None, (), DEFAULT_MAX_SECONDS
    valid = tuple(state.get("valid_targets") or ())
    target = state.get("target")
    max_seconds = float(state.get("max_seconds") or DEFAULT_MAX_SECONDS)
    return (target if target in valid else None), valid, max_seconds


def read_daemon_state():
    return json.loads(DAEMON_STATE_PATH.read_text())


def execute_switch(target):
    log("idle gap found, executing switch to %s" % target)
    result = subprocess.run(
        [str(DARKBLOOM_BIN), "start", "--model", target, "--idle-timeout", "0"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0 and "Input/output error" in (result.stderr or ""):
        log("bootstrap race detected, waiting 25s before retry: %s" % result.stderr.strip())
        time.sleep(25)
        result = subprocess.run(
            [str(DARKBLOOM_BIN), "start", "--model", target, "--idle-timeout", "0"],
            capture_output=True, text=True, timeout=60,
        )
    if result.returncode != 0:
        log("switch to %s FAILED: %s" % (target, result.stderr.strip()))
        return False
    log("switch command for %s returned success, verifying..." % target)
    for _ in range(5):
        time.sleep(3)
        state = read_daemon_state()
        if state.get("current_model") == target:
            log("post-switch verification: current_model=%s ok=True" % target)
            return True
    log("post-switch verification: current_model=%s ok=False (gave up after 15s)" % state.get("current_model"))
    return False


def main():
    acquire_lock_or_exit()
    try:
        _, _, max_seconds = read_target_state()
        deadline = time.time() + max_seconds
        while time.time() < deadline:
            target, _valid, _ = read_target_state()
            state = read_daemon_state()
            current = state.get("current_model")
            if target is None or target == current:
                time.sleep(POLL_SECONDS)
                continue
            if not state.get("inference_active", True):
                execute_switch(target)
                return
            time.sleep(POLL_SECONDS)
        log("timed out this cycle without an idle gap opening")
    finally:
        try:
            LOCK_FILE.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
