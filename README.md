# timelog

A small command-line time tracker. Start a task, stop it, and see where your
hours actually went — no account, no server, just a JSON file.

## Why

Timers in apps disappear when the app does. `timelog` keeps every session in
`~/.timelog.json`, a plain file you can read, back up, or grep. It answers the
one question that matters at the end of the day: *what did I spend time on?*

## Install

```sh
cp timelog.py ~/bin/timelog
chmod +x ~/bin/timelog
```

Requires Python 3.8+ and nothing else — standard library only.

## Usage

```sh
timelog start "CMPUT 365 assignment"
timelog status
timelog stop
timelog list
timelog report --today
timelog report --week
timelog report --all --task "gym"
```

- `start <task>` — starts timing. If another task is running, it is stopped
  first and logged, so you never lose time to a forgotten timer.
- `stop` — stops the running task and prints how long it took.
- `cancel` — discards the running task without logging it.
- `status` — shows the running task and elapsed time.
- `list [--limit N]` — recent sessions, newest first.
- `report [--today | --week | --all] [--task NAME]` — total time per task.
  Sessions that straddle a period boundary count only for the part inside it.

Backdate a start or stop with `--at HH:MM` (useful when you forgot to start
the timer):

```sh
timelog start "study" --at 09:30
timelog stop --at 11:00
```

## Data

Sessions live in `~/.timelog.json` (override with `--data PATH` or the
`TIMELOG_FILE` environment variable). Format:

```json
[
  {"task": "study", "start": 1763352000, "end": 1763355600}
]
```

A session with `"end": null` is the currently running task.

## Tests

```sh
python3 -m pytest tests/ -v
```

25 tests, covering start/stop/cancel, backdating, listing, and today/week/
all-time reports (including sessions that cross midnight and week boundaries).
