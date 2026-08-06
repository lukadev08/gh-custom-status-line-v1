#!/usr/bin/env python3
"""Render a compact GitHub Copilot CLI status line from JSON on stdin."""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


RESET = "\033[0m"
PURPLE = "\033[38;2;163;113;247m"
BLUE = "\033[38;2;88;166;255m"
GREEN = "\033[38;2;63;185;80m"
YELLOW = "\033[38;2;210;153;34m"
RED = "\033[38;2;248;81;73m"
MUTED = "\033[38;2;139;148;158m"
ANSI_RE = re.compile(r"\033\[[0-9;]*m")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def paint(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


def number(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def clean(text: str) -> str:
    return CONTROL_RE.sub("", text)


def compact(value: float) -> str:
    for divisor, suffix in ((1_000_000, "m"), (1_000, "k")):
        if abs(value) >= divisor:
            return f"{value / divisor:.1f}".rstrip("0").rstrip(".") + suffix
    return str(int(value))


def duration(milliseconds: float) -> str:
    seconds = max(0, int(milliseconds // 1000))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def context_color(percent: float) -> str:
    if percent >= 80:
        return RED
    if percent >= 50:
        return YELLOW
    return GREEN


def run_git(cwd: str, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=0.5,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def git_info(cwd: str) -> tuple[str, str, bool] | None:
    root = run_git(cwd, "rev-parse", "--show-toplevel")
    if not root:
        return None
    branch = run_git(cwd, "branch", "--show-current")
    if not branch:
        branch = run_git(cwd, "rev-parse", "--short", "HEAD") or ""
    status = run_git(cwd, "status", "--porcelain", "--untracked-files=normal")
    if status is None:
        return None
    return Path(root).name, branch, bool(status)


def render(payload: dict[str, Any]) -> str:
    segments: list[str] = []
    model = payload.get("model") if isinstance(payload.get("model"), dict) else {}
    context = payload.get("context_window") if isinstance(payload.get("context_window"), dict) else {}
    cost = payload.get("cost") if isinstance(payload.get("cost"), dict) else {}

    display_name = model.get("display_name")
    if isinstance(display_name, str) and display_name:
        segments.append(paint(f"󰚩 {clean(display_name)}", PURPLE))

    current = number(context.get("current_context_tokens"))
    limit = number(context.get("displayed_context_limit"))
    percent = number(context.get("current_context_used_percentage"))
    if percent is None and current is not None and limit and limit > 0:
        percent = current / limit * 100
    if current is not None and current >= 0 and limit is not None and limit > 0 and percent is not None:
        percent = max(0, min(100, percent))
        filled = min(10, int(percent // 10))
        gauge = "▰" * filled + "▱" * (10 - filled)
        segments.append(
            paint(f"󰘦 {compact(current)}/{compact(limit)} {percent:.0f}% {gauge}", context_color(percent))
        )

    requests = number(cost.get("total_premium_requests"))
    if requests is not None and requests >= 0:
        segments.append(paint(f"󱐋 {int(requests)}", YELLOW))

    total_ms = number(cost.get("total_duration_ms"))
    api_ms = number(cost.get("total_api_duration_ms"))
    if total_ms is not None or api_ms is not None:
        parts = []
        if total_ms is not None:
            parts.append(duration(total_ms))
        if api_ms is not None:
            parts.append(f"API{duration(api_ms)}")
        segments.append(paint(f"󰔛 {'·'.join(parts)}", BLUE))

    cwd = payload.get("cwd")
    if not isinstance(cwd, str):
        workspace = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
        cwd = workspace.get("current_dir")
    if isinstance(cwd, str) and (info := git_info(cwd)):
        repo, branch, dirty = info
        workspace_text = paint(f" {clean(repo)}", BLUE)
        if branch:
            workspace_text += " " + paint(
                f" {clean(branch)}{'*' if dirty else ''}", YELLOW if dirty else GREEN
            )
        segments.append(workspace_text)

    added = int(number(cost.get("total_lines_added")) or 0)
    removed = int(number(cost.get("total_lines_removed")) or 0)
    if added or removed:
        segments.append(
            paint("󰙏 ", MUTED) + paint(f"+{added}", GREEN) + paint(f"/-{removed}", RED)
        )

    remote = payload.get("remote") if isinstance(payload.get("remote"), dict) else {}
    if remote.get("connected") is True:
        segments.append(paint(" remote", BLUE))

    return paint(" │ ", MUTED).join(segments)


def parse_payload(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        return None


def self_test() -> None:
    payload = {
        "cwd": "/path/that/does/not/exist",
        "model": {"display_name": "GPT-5.4·med"},
        "context_window": {
            "current_context_tokens": 123_500,
            "displayed_context_limit": 200_000,
            "current_context_used_percentage": 61,
        },
        "cost": {
            "total_premium_requests": 7,
            "total_duration_ms": 754_000,
            "total_api_duration_ms": 108_000,
            "total_lines_added": 42,
            "total_lines_removed": 8,
        },
    }
    expected = (
        "󰚩 GPT-5.4·med │ 󰘦 123.5k/200k 61% ▰▰▰▰▰▰▱▱▱▱ │ 󱐋 7 │ "
        "󰔛 12m34s·API1m48s │ 󰙏 +42/-8"
    )
    assert ANSI_RE.sub("", render(payload)) == expected
    assert render({}) == ""
    assert parse_payload("not json") is None
    assert parse_payload("[]") is None
    assert number(float("nan")) is None and number(float("inf")) is None
    assert clean("one\nline\033[31m") == "oneline[31m"
    assert [context_color(value) for value in (49, 50, 79, 80)] == [GREEN, YELLOW, YELLOW, RED]

    with tempfile.TemporaryDirectory() as directory:
        subprocess.run(["git", "init", "-q", directory], check=True)
        subprocess.run(["git", "-C", directory, "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
        tracked = Path(directory, "tracked.txt")
        tracked.write_text("clean\n")
        subprocess.run(["git", "-C", directory, "add", "tracked.txt"], check=True)
        subprocess.run(
            ["git", "-C", directory, "-c", "user.name=Self Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "initial"],
            check=True,
        )
        clean_git = git_info(directory)
        assert clean_git and clean_git[1:] == ("main", False)
        tracked.write_text("dirty\n")
        dirty = git_info(directory)
        assert dirty and dirty[1:] == ("main", True)
        subprocess.run(["git", "-C", directory, "restore", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", directory, "checkout", "--detach", "-q"], check=True)
        detached = git_info(directory)
        assert detached and detached[1] != "main" and not detached[2]

    with tempfile.TemporaryDirectory() as directory:
        assert git_info(directory) is None

    print("self-test: ok")


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return 0
    if sys.argv[1:]:
        return 2
    payload = parse_payload(sys.stdin.read())
    if payload is not None:
        sys.stdout.write(render(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
