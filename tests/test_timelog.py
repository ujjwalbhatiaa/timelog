"""Tests for timelog (run with: python3 -m pytest tests/ -v)."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import timelog  # noqa: E402

# 2026-11-17 08:00 local (a Tuesday) as the fixed "now" for tests.
T0 = 1794000000  # placeholder, replaced below
from datetime import datetime  # noqa: E402

T0 = int(datetime(2026, 11, 17, 8, 0, 0).timestamp())
HOUR = 3600


@pytest.fixture
def data_file(tmp_path):
    return str(tmp_path / "timelog.json")


def run(argv, data_file, now=T0):
    """Run main() with --data pointed at the fixture; returns (code, out)."""
    import io
    from contextlib import redirect_stdout, redirect_stderr

    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        code = timelog.main(["--data", data_file] + argv, now=now)
    return code, buf_out.getvalue() + buf_err.getvalue()


def read(data_file):
    with open(data_file, encoding="utf-8") as fh:
        return json.load(fh)


# --- start / stop / status ---

def test_start_creates_running_session(data_file):
    code, out = run(["start", "study"], data_file)
    assert code == 0
    assert "Started 'study'" in out
    sessions = read(data_file)
    assert len(sessions) == 1
    assert sessions[0]["task"] == "study"
    assert sessions[0]["start"] == T0
    assert sessions[0]["end"] is None


def test_status_when_nothing_running(data_file):
    code, out = run(["status"], data_file)
    assert code == 0
    assert "No task running" in out


def test_status_shows_elapsed(data_file):
    run(["start", "study"], data_file)
    code, out = run(["status"], data_file, now=T0 + 30 * 60)
    assert code == 0
    assert "study" in out
    assert "30m 00s" in out


def test_stop_closes_session(data_file):
    run(["start", "study"], data_file)
    code, out = run(["stop"], data_file, now=T0 + 45 * 60)
    assert code == 0
    assert "45m 00s" in out
    sessions = read(data_file)
    assert sessions[0]["end"] == T0 + 45 * 60


def test_stop_with_nothing_running_errors(data_file):
    code, out = run(["stop"], data_file)
    assert code == 2
    assert "no task is running" in out


def test_start_while_running_stops_previous(data_file):
    run(["start", "study"], data_file)
    code, out = run(["start", "gym"], data_file, now=T0 + HOUR)
    assert code == 0
    assert "Stopped 'study'" in out
    assert "Started 'gym'" in out
    sessions = read(data_file)
    assert sessions[0]["end"] == T0 + HOUR
    assert sessions[1]["task"] == "gym"
    assert sessions[1]["end"] is None


def test_cancel_discards_running_task(data_file):
    run(["start", "study"], data_file)
    code, out = run(["cancel"], data_file)
    assert code == 0
    assert "Cancelled 'study'" in out
    assert read(data_file) == []


def test_cancel_with_nothing_running_errors(data_file):
    code, out = run(["cancel"], data_file)
    assert code == 2
    assert "no task is running" in out


# --- --at backdating ---

def test_start_with_at_backdates(data_file):
    code, out = run(["start", "study", "--at", "07:30"], data_file)
    assert code == 0
    sessions = read(data_file)
    assert sessions[0]["start"] == int(
        datetime(2026, 11, 17, 7, 30).timestamp())


def test_stop_with_at_backdates(data_file):
    run(["start", "study", "--at", "07:00"], data_file)
    code, out = run(["stop", "--at", "07:45"], data_file)
    assert code == 0
    assert "45m 00s" in out


def test_bad_at_value_errors(data_file):
    code, out = run(["start", "study", "--at", "25:99"], data_file)
    assert code == 2
    assert "invalid --at" in out


def test_stop_before_start_errors(data_file):
    run(["start", "study", "--at", "07:30"], data_file)
    code, out = run(["stop", "--at", "07:00"], data_file)
    assert code == 2
    assert "before the task started" in out


# --- list / report ---

def _seed_two_sessions(data_file):
    run(["start", "study", "--at", "06:00"], data_file)
    run(["stop", "--at", "07:00"], data_file)
    run(["start", "gym", "--at", "07:30"], data_file)
    run(["stop", "--at", "08:00"], data_file, now=T0 + 30 * 60)


def test_list_shows_finished_sessions(data_file):
    _seed_two_sessions(data_file)
    code, out = run(["list"], data_file, now=T0 + HOUR)
    assert code == 0
    assert "study" in out and "1h 00m" in out
    assert "gym" in out and "30m 00s" in out


def test_list_empty(data_file):
    code, out = run(["list"], data_file)
    assert code == 0
    assert "No sessions logged yet" in out


def test_list_limit(data_file):
    _seed_two_sessions(data_file)
    code, out = run(["list", "--limit", "1"], data_file, now=T0 + HOUR)
    assert code == 0
    assert "gym" in out
    assert "study" not in out


def test_report_today_totals(data_file):
    _seed_two_sessions(data_file)
    code, out = run(["report", "--today"], data_file, now=T0 + HOUR)
    assert code == 0
    assert "study" in out and "1h 00m" in out
    assert "gym" in out and "30m 00s" in out
    assert "TOTAL" in out and "1h 30m" in out


def test_report_task_filter(data_file):
    _seed_two_sessions(data_file)
    code, out = run(["report", "--today", "--task", "gym"], data_file,
                    now=T0 + HOUR)
    assert code == 0
    assert "gym" in out
    assert "study" not in out


def test_report_empty(data_file):
    code, out = run(["report", "--today"], data_file)
    assert code == 0
    assert "No finished sessions" in out


def test_report_week_groups_across_days(data_file):
    # A session on Monday (Nov 16) still counts in this week's report.
    monday = int(datetime(2026, 11, 16, 10, 0).timestamp())
    run(["start", "study", "--at", "10:00"], data_file, now=monday)
    run(["stop", "--at", "11:00"], data_file, now=monday + HOUR)
    code, out = run(["report", "--week"], data_file, now=T0 + HOUR)
    assert code == 0
    assert "study" in out and "1h 00m" in out
    # ...but not in today's report (Tuesday).
    code, out = run(["report", "--today"], data_file, now=T0 + HOUR)
    assert "No finished sessions" in out


def test_report_all_includes_old_sessions(data_file):
    monday = int(datetime(2026, 11, 16, 10, 0).timestamp())
    run(["start", "study", "--at", "10:00"], data_file, now=monday)
    run(["stop", "--at", "11:00"], data_file, now=monday + HOUR)
    code, out = run(["report", "--all"], data_file, now=T0 + HOUR)
    assert code == 0
    assert "study" in out and "1h 00m" in out


def test_running_session_excluded_from_report(data_file):
    run(["start", "study"], data_file)
    code, out = run(["report", "--today"], data_file, now=T0 + HOUR)
    assert code == 0
    assert "No finished sessions" in out


# --- formatting / persistence ---

def test_format_duration():
    assert timelog.format_duration(45) == "45s"
    assert timelog.format_duration(90) == "1m 30s"
    assert timelog.format_duration(3660) == "1h 01m"
    assert timelog.format_duration(7200) == "2h 00m"


def test_data_file_created_by_save(data_file):
    assert not os.path.exists(data_file)
    run(["start", "study"], data_file)
    assert os.path.exists(data_file)


def test_corrupt_data_file_errors(data_file):
    with open(data_file, "w", encoding="utf-8") as fh:
        fh.write('{"not": "a list"}')
    code, out = run(["status"], data_file)
    assert code == 2
    assert "corrupt" in out


def test_limit_zero_errors(data_file):
    code, out = run(["list", "--limit", "0"], data_file)
    assert code == 2
    assert "--limit must be at least 1" in out
