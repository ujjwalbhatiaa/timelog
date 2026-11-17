#!/usr/bin/env python3
"""timelog — a small command-line time tracker.

Track how long you spend on tasks, with sessions stored in a plain JSON
file so the data stays yours and stays readable.

Usage:
    timelog start <task> [--at HH:MM]   start timing a task
    timelog stop [--at HH:MM]           stop the running task
    timelog cancel                      discard the running task
    timelog status                      show the running task and elapsed time
    timelog list [--limit N]            list recent sessions
    timelog report [--today] [--week] [--task NAME] [--all]
                                        totals per task for a period

Data lives in ~/.timelog.json by default; override with --data PATH or the
TIMELOG_FILE environment variable. All times are local time.

Examples:
    timelog start "CMPUT 365 assignment"
    timelog stop
    timelog report --week
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta

VERSION = "1.0.0"
DEFAULT_DATA_FILE = os.path.join(os.path.expanduser("~"), ".timelog.json")


class TimelogError(Exception):
    """User-facing error (bad usage, bad state)."""


def default_data_file():
    return os.environ.get("TIMELOG_FILE", DEFAULT_DATA_FILE)


def load_sessions(path):
    """Return the list of session dicts stored at path (empty list if none)."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise TimelogError(f"data file {path} is corrupt: expected a list")
    for session in data:
        if not isinstance(session, dict) or "task" not in session \
                or "start" not in session or "end" not in session:
            raise TimelogError(f"data file {path} is corrupt: bad session")
    return data


def save_sessions(path, sessions):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(sessions, fh, indent=2)
        fh.write("\n")
    os.replace(tmp_path, path)


def running_session(sessions):
    """Return the currently running session dict, or None."""
    for session in reversed(sessions):
        if session["end"] is None:
            return session
    return None


def parse_at(value, now):
    """Parse an --at HH:MM time into an epoch timestamp today (or yesterday
    if that time is in the future relative to now)."""
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except ValueError:
        raise TimelogError(f"invalid --at value {value!r}: use HH:MM")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise TimelogError(f"invalid --at value {value!r}: use HH:MM")
    today = datetime.fromtimestamp(now)
    stamp = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if stamp.timestamp() > now:
        stamp -= timedelta(days=1)
    return stamp.timestamp()


def format_duration(seconds):
    """Format a duration in seconds as e.g. '2h 05m' or '45m 30s'."""
    seconds = int(round(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def format_time(epoch):
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")


def start_task(sessions, task, now, at=None):
    """Start timing task. Stops any running task first. Returns a message."""
    stamp = at if at is not None else now
    current = running_session(sessions)
    message = ""
    if current is not None:
        current["end"] = stamp
        message = (f"Stopped '{current['task']}' "
                   f"({format_duration(stamp - current['start'])}).\n")
    if stamp < now - 86400 * 365:
        raise TimelogError("start time is more than a year in the past")
    sessions.append({"task": task, "start": stamp, "end": None})
    return message + f"Started '{task}' at {format_time(stamp)}."


def stop_task(sessions, now, at=None):
    """Stop the running task. Returns a message."""
    stamp = at if at is not None else now
    current = running_session(sessions)
    if current is None:
        raise TimelogError("no task is running")
    if stamp < current["start"]:
        raise TimelogError("stop time is before the task started")
    current["end"] = stamp
    return (f"Stopped '{current['task']}' — "
            f"{format_duration(stamp - current['start'])} "
            f"({format_time(current['start'])} → {format_time(stamp)}).")


def cancel_task(sessions):
    """Discard the running task without logging it. Returns a message."""
    current = running_session(sessions)
    if current is None:
        raise TimelogError("no task is running")
    sessions.remove(current)
    return f"Cancelled '{current['task']}' (not logged)."


def status_text(sessions, now):
    current = running_session(sessions)
    if current is None:
        return "No task running."
    return (f"Running: '{current['task']}' — "
            f"{format_duration(now - current['start'])} elapsed "
            f"(since {format_time(current['start'])}).")


def list_text(sessions, now, limit=10):
    """Recent sessions, newest first. The running task (if any) is shown live."""
    lines = []
    finished = [s for s in sessions if s["end"] is not None]
    for session in reversed(finished[-limit:]):
        lines.append(f"{format_time(session['start'])}  "
                     f"{session['task']:<30} "
                     f"{format_duration(session['end'] - session['start'])}")
    current = running_session(sessions)
    if current is not None:
        lines.append(f"{format_time(current['start'])}  "
                     f"{current['task']:<30} "
                     f"{format_duration(now - current['start'])} (running)")
    return "\n".join(lines) if lines else "No sessions logged yet."


def report_totals(sessions, start_epoch, end_epoch, task_filter=None):
    """Total seconds per task for finished sessions overlapping the window.

    A session counts for the part of it inside [start_epoch, end_epoch).
    The running session is excluded (it has no end yet).
    """
    totals = {}
    for session in sessions:
        if session["end"] is None:
            continue
        if task_filter is not None and session["task"] != task_filter:
            continue
        overlap_start = max(session["start"], start_epoch)
        overlap_end = min(session["end"], end_epoch)
        if overlap_end <= overlap_start:
            continue
        totals[session["task"]] = totals.get(session["task"], 0.0) \
            + (overlap_end - overlap_start)
    return totals


def report_text(sessions, now, period, task_filter=None):
    """Totals per task for a period: 'today', 'week', or 'all'."""
    if period == "today":
        start = datetime.fromtimestamp(now).replace(
            hour=0, minute=0, second=0, microsecond=0).timestamp()
        end = start + 86400
        label = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
    elif period == "week":
        today = datetime.fromtimestamp(now).replace(
            hour=0, minute=0, second=0, microsecond=0)
        start = (today - timedelta(days=today.weekday())).timestamp()
        end = start + 7 * 86400
        label = (f"week of "
                 f"{datetime.fromtimestamp(start).strftime('%Y-%m-%d')}")
    else:  # all
        start, end = 0.0, float("inf")
        label = "all time"
    totals = report_totals(sessions, start, end, task_filter)
    if not totals:
        return f"No finished sessions for {label}."
    lines = [f"Time report — {label}:"]
    grand = 0.0
    for task, seconds in sorted(totals.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {task:<30} {format_duration(seconds)}")
        grand += seconds
    lines.append(f"  {'TOTAL':<30} {format_duration(grand)}")
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="timelog", description="Track time spent on tasks.")
    parser.add_argument("--data", default=None,
                        help="data file (default ~/.timelog.json or "
                        "$TIMELOG_FILE)")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="start timing a task")
    p_start.add_argument("task", help="task name")
    p_start.add_argument("--at", default=None,
                         help="backdate the start, HH:MM today")

    p_stop = sub.add_parser("stop", help="stop the running task")
    p_stop.add_argument("--at", default=None,
                        help="backdate the stop, HH:MM today")

    sub.add_parser("cancel", help="discard the running task")
    sub.add_parser("status", help="show the running task")

    p_list = sub.add_parser("list", help="list recent sessions")
    p_list.add_argument("--limit", type=int, default=10,
                        help="how many sessions to show (default 10)")

    p_report = sub.add_parser("report", help="totals per task")
    group = p_report.add_mutually_exclusive_group()
    group.add_argument("--today", action="store_true",
                       help="today only (default)")
    group.add_argument("--week", action="store_true",
                       help="this calendar week (Mon–Sun)")
    group.add_argument("--all", action="store_true", help="all time")
    p_report.add_argument("--task", default=None,
                          help="only totals for this task")
    return parser


def main(argv=None, now=None):
    """Entry point. `now` is injectable (epoch seconds) for tests."""
    args = build_parser().parse_args(argv)
    if now is None:
        now = time.time()
    data_file = args.data or default_data_file()
    try:
        sessions = load_sessions(data_file)
        if args.command == "start":
            at = parse_at(args.at, now) if args.at else None
            out = start_task(sessions, args.task, now, at)
        elif args.command == "stop":
            at = parse_at(args.at, now) if args.at else None
            out = stop_task(sessions, now, at)
        elif args.command == "cancel":
            out = cancel_task(sessions)
        elif args.command == "status":
            out = status_text(sessions, now)
            print(out)
            return 0
        elif args.command == "list":
            if args.limit < 1:
                raise TimelogError("--limit must be at least 1")
            out = list_text(sessions, now, args.limit)
            print(out)
            return 0
        elif args.command == "report":
            period = "week" if args.week else "all" if args.all else "today"
            out = report_text(sessions, now, period, args.task)
            print(out)
            return 0
        else:  # pragma: no cover - argparse enforces a command
            raise TimelogError("unknown command")
        save_sessions(data_file, sessions)
        print(out)
        return 0
    except TimelogError as exc:
        print(f"timelog: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
