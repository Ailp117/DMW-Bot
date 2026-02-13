from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass


log = logging.getLogger("dmw.runner")


@dataclass(slots=True)
class RunnerConfig:
    target_script: str
    max_runtime_seconds: int
    restart_delay_seconds: int
    max_backoff_seconds: int
    min_uptime_seconds: int
    max_quick_failures: int


class BotRunner:
    def __init__(self, config: RunnerConfig) -> None:
        self.config = config
        self._stop_requested = False
        self._child: subprocess.Popen[bytes] | None = None

    def request_stop(self, signum: int, _frame) -> None:
        log.warning("Received signal %s, stopping runner.", signum)
        self._stop_requested = True
        self._terminate_child()

    def _terminate_child(self) -> None:
        child = self._child
        if child is None or child.poll() is not None:
            return

        log.info("Stopping child process pid=%s", child.pid)
        child.terminate()
        try:
            child.wait(timeout=25)
            return
        except subprocess.TimeoutExpired:
            log.warning("Child did not stop in time, killing pid=%s", child.pid)
            child.kill()
            child.wait(timeout=10)

    def run(self) -> int:
        self._install_signal_handlers()

        started_at = time.monotonic()
        backoff_seconds = max(1, self.config.restart_delay_seconds)
        quick_failures = 0

        while not self._stop_requested:
            runtime_elapsed = time.monotonic() - started_at
            if self.config.max_runtime_seconds > 0 and runtime_elapsed >= self.config.max_runtime_seconds:
                log.info("Max runtime reached (%ss).", self.config.max_runtime_seconds)
                self._terminate_child()
                return 0

            cmd = [sys.executable, self.config.target_script]
            log.info("Starting child bot process: %s", " ".join(cmd))
            child_started_at = time.monotonic()
            self._child = subprocess.Popen(cmd)

            exit_code = self._wait_for_child_or_timeout(started_at)
            uptime = int(time.monotonic() - child_started_at)

            if self._stop_requested:
                return 0

            if exit_code == 0:
                log.info("Child exited cleanly (code=0).")
            else:
                log.error("Child exited with code=%s after %ss", exit_code, uptime)

            if uptime < self.config.min_uptime_seconds:
                quick_failures += 1
                log.warning(
                    "Quick failure detected (%s/%s, uptime=%ss < %ss).",
                    quick_failures,
                    self.config.max_quick_failures,
                    uptime,
                    self.config.min_uptime_seconds,
                )
            else:
                quick_failures = 0
                backoff_seconds = max(1, self.config.restart_delay_seconds)

            if quick_failures > self.config.max_quick_failures:
                log.error("Too many quick failures, aborting runner.")
                return exit_code if exit_code != 0 else 1

            log.info("Restarting child in %ss", backoff_seconds)
            time.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, self.config.max_backoff_seconds)

        self._terminate_child()
        return 0

    def _wait_for_child_or_timeout(self, started_at: float) -> int:
        assert self._child is not None

        while True:
            if self._stop_requested:
                self._terminate_child()
                return self._child.poll() or 0

            runtime_elapsed = time.monotonic() - started_at
            if self.config.max_runtime_seconds > 0 and runtime_elapsed >= self.config.max_runtime_seconds:
                self._terminate_child()
                return 0

            code = self._child.poll()
            if code is not None:
                return code
            time.sleep(1)

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DMW bot runner with auto-restart.")
    parser.add_argument(
        "--target-script",
        default=os.getenv("BOT_RUNNER_TARGET", "bot/runtime.py"),
        help="Python script to execute as bot process.",
    )
    parser.add_argument(
        "--max-runtime-seconds",
        type=int,
        default=int(os.getenv("BOT_RUNNER_MAX_RUNTIME_SECONDS", "21420")),
        help="Maximum runner lifetime before graceful stop (0 disables).",
    )
    parser.add_argument(
        "--restart-delay-seconds",
        type=int,
        default=int(os.getenv("BOT_RUNNER_RESTART_DELAY_SECONDS", "5")),
        help="Initial restart delay after child failure.",
    )
    parser.add_argument(
        "--max-backoff-seconds",
        type=int,
        default=int(os.getenv("BOT_RUNNER_MAX_BACKOFF_SECONDS", "120")),
        help="Maximum exponential backoff between restart attempts.",
    )
    parser.add_argument(
        "--min-uptime-seconds",
        type=int,
        default=int(os.getenv("BOT_RUNNER_MIN_UPTIME_SECONDS", "20")),
        help="Child uptime threshold used for quick-failure detection.",
    )
    parser.add_argument(
        "--max-quick-failures",
        type=int,
        default=int(os.getenv("BOT_RUNNER_MAX_QUICK_FAILURES", "6")),
        help="Abort after this many consecutive quick failures.",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("BOT_RUNNER_LOG_LEVEL", "INFO"),
        help="Runner log level.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = RunnerConfig(
        target_script=args.target_script,
        max_runtime_seconds=max(0, args.max_runtime_seconds),
        restart_delay_seconds=max(1, args.restart_delay_seconds),
        max_backoff_seconds=max(1, args.max_backoff_seconds),
        min_uptime_seconds=max(1, args.min_uptime_seconds),
        max_quick_failures=max(0, args.max_quick_failures),
    )

    runner = BotRunner(config)
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
