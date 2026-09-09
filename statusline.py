#!/usr/bin/env python3
"""Render a compact GitHub Copilot CLI status line from JSON on stdin."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen


RESET = "\033[0m"
PURPLE = "\033[38;2;163;113;247m"
BLUE = "\033[38;2;88;166;255m"
GREEN = "\033[38;2;63;185;80m"
YELLOW = "\033[38;2;210;153;34m"
RED = "\033[38;2;248;81;73m"
MUTED = "\033[38;2;139;148;158m"
ANSI_RE = re.compile(r"\033\[[0-9;]*m")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
DECIMAL_RE = re.compile(r"\d+(?:\.\d+)?")
SESSION_EVENT_TYPES = {
    "session.compaction_complete",
    "session.usage_checkpoint",
    "session.shutdown",
}


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


def fetch_headroom_quota() -> dict[str, Any] | None:
    """Read Headroom's in-memory quota snapshot without handling credentials here."""
    try:
        quota_url = os.environ.get("HEADROOM_QUOTA_URL", "").strip()
        if not quota_url:
            for key in ("COPILOT_PROVIDER_BASE_URL", "COPILOT_API_URL"):
                try:
                    parsed = urlsplit(os.environ.get(key, "").strip())
                except ValueError:
                    continue
                if (
                    parsed.scheme in {"http", "https"}
                    and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                    and not parsed.username
                ):
                    quota_url = urlunsplit((parsed.scheme, parsed.netloc, "/quota", "", ""))
                    break
            if not quota_url:
                return None

        parsed = urlsplit(quota_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
            return None
        if parsed.path in {"", "/"}:
            quota_url = urlunsplit((parsed.scheme, parsed.netloc, "/quota", "", ""))
        with urlopen(quota_url, timeout=0.3) as response:
            raw = response.read(65_537)
        if len(raw) > 65_536:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def quota_segment(data: dict[str, Any]) -> str | None:
    state = data.get("copilot_quota")
    if not isinstance(state, dict) or not isinstance(state.get("latest"), dict):
        return None
    categories = state["latest"].get("categories")
    if not isinstance(categories, dict):
        return None
    quota = categories.get("premium_interactions")
    if not isinstance(quota, dict):
        return None
    if quota.get("unlimited") is True:
        return paint("quota ∞", GREEN)

    percent = number(quota.get("percent_remaining"))
    if percent is None:
        remaining = number(quota.get("remaining"))
        entitlement = number(quota.get("entitlement"))
        if remaining is None or entitlement is None or entitlement <= 0:
            return None
        percent = remaining / entitlement * 100
    percent = max(0, min(100, percent))
    rounded = min(100, int(percent + 0.5))
    filled = min(10, rounded // 10)
    gauge = "█" * filled + "░" * (10 - filled)
    return paint(f"quota {rounded}% {gauge}", context_color(100 - rounded))


def session_event_metrics(transcript_path: Any) -> tuple[float | None, int | None]:
    if not isinstance(transcript_path, str) or not transcript_path:
        return None, None
    try:
        root = (Path(os.environ.get("COPILOT_HOME", Path.home() / ".copilot")) / "session-state").resolve()
        path = Path(transcript_path).resolve()
        events = (path / "events.jsonl" if path.is_dir() else path).resolve()
        if root not in events.parents or events.name != "events.jsonl":
            return None, None

        nano_aiu = None
        compactions = 0
        with events.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if '"session.' not in line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type") if isinstance(event, dict) else None
                if event_type not in SESSION_EVENT_TYPES:
                    continue
                data = event.get("data")
                if not isinstance(data, dict):
                    continue
                if event_type == "session.compaction_complete":
                    if data.get("success") is True:
                        compactions += 1
                    continue
                value = number(data.get("totalNanoAiu"))
                if value is not None and value >= 0:
                    nano_aiu = value
        return nano_aiu, compactions
    except (OSError, ValueError):
        return None, None


def ai_credits(payload: dict[str, Any], fallback_nano_aiu: float | None) -> str | None:
    usage = payload.get("ai_used") if isinstance(payload.get("ai_used"), dict) else {}
    formatted = usage.get("formatted")
    if isinstance(formatted, str) and DECIMAL_RE.fullmatch(formatted):
        return formatted

    nano_aiu = number(usage.get("total_nano_aiu"))
    if nano_aiu is None:
        nano_aiu = fallback_nano_aiu
    if nano_aiu is None or nano_aiu < 0:
        return None
    return f"{nano_aiu / 1_000_000_000:.3f}".rstrip("0").rstrip(".")


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


def render(payload: dict[str, Any], headroom_quota: dict[str, Any] | None = None) -> str:
    segments: list[str] = []
    model = payload.get("model") if isinstance(payload.get("model"), dict) else {}
    context = payload.get("context_window") if isinstance(payload.get("context_window"), dict) else {}
    cost = payload.get("cost") if isinstance(payload.get("cost"), dict) else {}

    display_name = model.get("display_name")
    if isinstance(display_name, str) and display_name:
        segments.append(paint(clean(display_name), PURPLE))

    current = number(context.get("current_context_tokens"))
    limit = number(context.get("displayed_context_limit"))
    percent = number(context.get("current_context_used_percentage"))
    if percent is None and current is not None and limit and limit > 0:
        percent = current / limit * 100
    if current is not None and current >= 0 and limit is not None and limit > 0 and percent is not None:
        percent = max(0, min(100, percent))
        filled = min(10, int(percent // 10))
        gauge = "█" * filled + "░" * (10 - filled)
        segments.append(
            paint(f"ctx {compact(current)}/{compact(limit)} {percent:.0f}% {gauge}", context_color(percent))
        )

    nano_aiu, compactions = session_event_metrics(payload.get("transcript_path"))
    credits = ai_credits(payload, nano_aiu)
    if credits is not None:
        segments.append(paint(f"AIC {credits}", YELLOW))
    else:
        requests = number(cost.get("total_premium_requests"))
        if requests is not None and requests >= 0:
            segments.append(paint(f"req {int(requests)}", YELLOW))

    if compactions is not None:
        segments.append(paint(f"cmp {compactions}", PURPLE))

    cwd = payload.get("cwd")
    if not isinstance(cwd, str):
        workspace = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
        cwd = workspace.get("current_dir")
    if isinstance(cwd, str) and (info := git_info(cwd)):
        repo, branch, dirty = info
        workspace_text = paint(clean(repo), BLUE)
        if branch:
            workspace_text += " " + paint(
                f"{clean(branch)}{'*' if dirty else ''}", YELLOW if dirty else GREEN
            )
        segments.append(workspace_text)

    added = int(number(cost.get("total_lines_added")) or 0)
    removed = int(number(cost.get("total_lines_removed")) or 0)
    if added or removed:
        segments.append(paint(f"+{added}", GREEN) + paint(f"/-{removed}", RED))

    remote = payload.get("remote") if isinstance(payload.get("remote"), dict) else {}
    if remote.get("connected") is True:
        segments.append(paint("remote", BLUE))

    if headroom_quota is not None and (quota := quota_segment(headroom_quota)):
        segments.append(quota)

    total_ms = number(cost.get("total_duration_ms"))
    api_ms = number(cost.get("total_api_duration_ms"))
    if total_ms is not None or api_ms is not None:
        parts = []
        if total_ms is not None:
            parts.append(duration(total_ms))
        if api_ms is not None:
            parts.append(f"API {duration(api_ms)}")
        segments.append(paint(" ".join(parts), BLUE))

    return paint(" | ", MUTED).join(segments)


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
        "GPT-5.4·med | ctx 123.5k/200k 61% ██████░░░░ | req 7 | "
        "+42/-8 | 12m34s API 1m48s"
    )
    rendered = ANSI_RE.sub("", render(payload))
    assert rendered == expected
    usage_payload = {**payload, "ai_used": {"formatted": "2.75", "total_nano_aiu": 2_750_000_000}}
    with_credits = ANSI_RE.sub("", render(usage_payload))
    assert " | AIC 2.75 | " in with_credits and "req 7" not in with_credits
    assert ai_credits({"ai_used": {"total_nano_aiu": 1_250_000_000}}, None) == "1.25"
    headroom_quota = {
        "copilot_quota": {
            "latest": {
                "categories": {
                    "premium_interactions": {
                        "entitlement": 300,
                        "remaining": 219,
                        "percent_remaining": 73,
                    }
                }
            }
        }
    }
    with_quota = ANSI_RE.sub("", render(payload, headroom_quota))
    assert with_quota.endswith(" | quota 73% ███████░░░ | 12m34s API 1m48s")
    from unittest.mock import MagicMock, patch

    provider_url = "http://127.0.0.1:8787/v1"
    native_url = "http://localhost:9876/p/project"
    for env, expected_url in (
        ({}, None),
        ({"COPILOT_PROVIDER_BASE_URL": provider_url}, "http://127.0.0.1:8787/quota"),
        ({"COPILOT_API_URL": native_url}, "http://localhost:9876/quota"),
        ({"COPILOT_API_URL": "http://[::1]:9876/p/project"}, "http://[::1]:9876/quota"),
        ({"COPILOT_API_URL": "https://api.example.com"}, None),
        ({"COPILOT_API_URL": "http://user:secret@localhost:9876"}, None),
        ({"COPILOT_PROVIDER_BASE_URL": "http://[", "COPILOT_API_URL": native_url}, "http://localhost:9876/quota"),
        ({"COPILOT_PROVIDER_BASE_URL": "https://api.example.com", "COPILOT_API_URL": native_url}, "http://localhost:9876/quota"),
        ({"COPILOT_PROVIDER_BASE_URL": provider_url, "COPILOT_API_URL": native_url}, "http://127.0.0.1:8787/quota"),
        ({"HEADROOM_QUOTA_URL": "http://localhost:7777/quota", "COPILOT_API_URL": native_url}, "http://localhost:7777/quota"),
    ):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(headroom_quota).encode()
        with patch.dict(os.environ, env, clear=True), patch(__name__ + ".urlopen", return_value=response) as request:
            snapshot = fetch_headroom_quota()
            if expected_url is None:
                assert snapshot is None
                request.assert_not_called()
            else:
                request.assert_called_once_with(expected_url, timeout=0.3)
                assert "quota 73%" in ANSI_RE.sub("", render(payload, snapshot))
    assert not any(0xE000 <= ord(char) <= 0xF8FF or 0xF0000 <= ord(char) <= 0xFFFFD for char in rendered)
    assert render({}) == ""
    assert parse_payload("not json") is None
    assert parse_payload("[]") is None
    assert number(float("nan")) is None and number(float("inf")) is None
    assert clean("one\nline\033[31m") == "oneline[31m"
    assert [context_color(value) for value in (49, 50, 79, 80)] == [GREEN, YELLOW, YELLOW, RED]

    with tempfile.TemporaryDirectory() as directory:
        previous_home = os.environ.get("COPILOT_HOME")
        os.environ["COPILOT_HOME"] = directory
        try:
            session = Path(directory, "session-state", "test-session")
            session.mkdir(parents=True)
            events = [
                {"id": "usage", "data": {"totalNanoAiu": 3_500_000_000}, "type": "session.usage_checkpoint"},
                {"type": "session.compaction_complete", "data": {"success": True}},
                {"type": "session.compaction_complete", "data": {"success": False}},
                {"type": "session.compaction_complete", "data": {"success": True}},
            ]
            Path(session, "events.jsonl").write_text(
                "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
            )
            assert session_event_metrics(str(session)) == (3_500_000_000, 2)
            session_payload = {**payload, "transcript_path": str(session)}
            rendered_session = ANSI_RE.sub("", render(session_payload))
            assert " | AIC 3.5 | cmp 2 | " in rendered_session and "req 7" not in rendered_session
            assert session_event_metrics("/tmp/events.jsonl") == (None, None)
        finally:
            if previous_home is None:
                os.environ.pop("COPILOT_HOME", None)
            else:
                os.environ["COPILOT_HOME"] = previous_home

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
        sys.stdout.write(render(payload, fetch_headroom_quota()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
