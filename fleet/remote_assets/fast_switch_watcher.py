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
(or removes) over SSH every tick, rather than take a fixed target - this
self-corrects if the recommendation changes mid-wait. A failed switch is
recorded, and the watcher waits out fleet's restart backoff before trying
again.

Standalone stdlib script: fleet copies this file verbatim to the remote host
and runs it there with the host's own python3, so it must not import the
fleet package or any third-party dependency.
"""
from __future__ import annotations

import fcntl
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
LOCK_FILE = WIDGET_DIR / "fast-switch.lock"
FAILED_AT_FILE = WIDGET_DIR / "fast-switch-failed-at"
POLL_SECONDS = 1
DEFAULT_MAX_SECONDS = 55


def acquire_lock_or_exit() -> int:
    """One watcher at a time: an exclusive flock on a private file that is not
    a symlink. The kernel releases it when the process exits, so a crashed
    watcher leaves no stale lock. Returns the descriptor, which must stay open."""
    try:
        fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        sys.exit(f"refusing lock file {LOCK_FILE}: {error}")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        sys.exit(0)  # another watcher is running
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    return fd


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}\n"
    with LOG.open("a") as f:
        f.write(line)
    print(line, end="")


def read_target_state() -> tuple[str | None, tuple[str, ...], float]:
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


def in_failure_backoff(now: float) -> bool:
    """True while the last failed switch is younger than fleet's restart backoff."""
    try:
        failed_at = float(FAILED_AT_FILE.read_text())
        backoff = float(json.loads(TARGET_STATE_PATH.read_text()).get("restart_backoff_seconds") or 0)
    except (FileNotFoundError, ValueError):
        return False
    return now - failed_at < backoff


def read_daemon_state() -> dict[str, object]:
    return json.loads(DAEMON_STATE_PATH.read_text())


def _daemon_state_or_none() -> dict[str, object] | None:
    """The daemon rewrites its state file in place; a missing or half-written
    file is a transient read, not a reason to stop watching."""
    try:
        return read_daemon_state()
    except (OSError, ValueError):
        return None


def _should_switch(target: str | None, state: dict[str, object] | None) -> bool:
    return (target is not None and state is not None
            and target != state.get("current_model") and not state.get("inference_active", True))


def _run_start(target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(DARKBLOOM_BIN), "start", "--model", target, "--idle-timeout", "0"],
        capture_output=True, text=True, timeout=60, check=False,
    )


def _verify(target: str) -> bool:
    current = None
    for _ in range(5):
        time.sleep(3)
        state = _daemon_state_or_none()
        current = state.get("current_model") if state else current
        if current == target:
            log(f"post-switch verification: current_model={target} ok=True")
            return True
    log(f"post-switch verification: current_model={current} ok=False (gave up after 15s)")
    return False


def execute_switch(target: str) -> bool:
    log(f"idle gap found, executing switch to {target}")
    result = _run_start(target)
    if result.returncode != 0 and "Input/output error" in (result.stderr or ""):
        log(f"bootstrap race detected, waiting 25s before retry: {result.stderr.strip()}")
        time.sleep(25)
        result = _run_start(target)
    if result.returncode != 0:
        log(f"switch to {target} FAILED: {result.stderr.strip()}")
        return False
    log(f"switch command for {target} returned success, verifying...")
    return _verify(target)


def _wait_for_idle_gap(deadline: float) -> str | None:
    """The target to switch to once the host is idle, or None at the deadline.
    Target and idleness are both re-read immediately before returning, so a
    withdrawn recommendation or a request that has just started always wins."""
    while time.time() < deadline:
        target = read_target_state()[0]
        if not _should_switch(target, _daemon_state_or_none()):
            time.sleep(POLL_SECONDS)
            continue
        if read_target_state()[0] == target and _should_switch(target, _daemon_state_or_none()):
            return target
    return None


def main() -> None:
    lock_fd = acquire_lock_or_exit()
    try:
        if in_failure_backoff(time.time()):
            log("a recent switch failed; waiting out the restart backoff")
            return
        target = _wait_for_idle_gap(time.time() + read_target_state()[2])
        if target is None:
            log("timed out this cycle without an idle gap opening")
        elif not execute_switch(target):
            FAILED_AT_FILE.write_text(str(time.time()))
    finally:
        os.close(lock_fd)


if __name__ == "__main__":  # pragma: no cover
    main()
