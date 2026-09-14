"""Command line entry point.

    poolstatus today            what is free today, and who has the rest
    poolstatus today --html     same, as HTML for an email body
    poolstatus week             the week ahead, and when to go
    poolstatus week --html      same, as HTML for an email body
    poolstatus snapshot         fetch and append to the local history
    poolstatus patterns         recurring bookings, and which are still unnamed
    poolstatus prefs            the swim preferences currently in force

Dates and times are the pool's, not the host's -- see preferences.toml.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from . import analyse, client, config, report, store
from .model import ENDS, WEEKDAY_NAMES, _h


def _when(value: str) -> dt.date:
    """A day to start the week from: today, tomorrow, or a plain date."""
    if value == "today":
        return config.today()
    if value == "tomorrow":
        return config.today() + dt.timedelta(days=1)
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected today, tomorrow or YYYY-MM-DD, got {value!r}"
        ) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="poolstatus", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    today = sub.add_parser("today", help="today's availability and who booked it")
    today.add_argument("--date", type=dt.date.fromisoformat, help="YYYY-MM-DD")
    today.add_argument("--html", action="store_true", help="emit HTML for an email")
    today.add_argument(
        "--all-day",
        action="store_true",
        help="include blocks that have already passed",
    )
    today.add_argument("--min-lanes", type=int, help="override preferences.toml")

    week = sub.add_parser("week", help="the week ahead, one timetable per day")
    week.add_argument("--days", type=int, default=7)
    week.add_argument(
        "--from",
        dest="start",
        type=_when,
        default="today",
        metavar="WHEN",
        help="today (default), tomorrow, or YYYY-MM-DD",
    )
    week.add_argument("--html", action="store_true", help="emit HTML for an email")
    week.add_argument(
        "--all-day",
        action="store_true",
        help="keep today's blocks that have already passed",
    )
    week.add_argument(
        "--window",
        metavar="FROM-TO",
        help="override the swim window in preferences.toml, e.g. 8:00-10:00",
    )
    week.add_argument("--min-lanes", type=int, help="override preferences.toml")

    snap = sub.add_parser("snapshot", help="fetch and append to the local history")
    snap.add_argument("--days", type=int, default=client.MAX_DAYS_AHEAD)

    pat = sub.add_parser("patterns", help="recurring bookings across the data we have")
    pat.add_argument(
        "--source",
        choices=("live", "history", "both"),
        default="both",
        help="live = the API's 4-week window, history = the local record",
    )
    pat.add_argument("--end", choices=ENDS, help="only one half of the pool")
    pat.add_argument(
        "--unnamed",
        action="store_true",
        help="only show bookings the rules do not explain",
    )

    prefs = sub.add_parser("prefs", help="the settings in preferences.toml, resolved")
    prefs.add_argument(
        "--timezone",
        action="store_true",
        help="print just the timezone -- what send_report.sh sets its clock by",
    )

    args = parser.parse_args(argv)

    if args.command == "today":
        return _today(args)
    if args.command == "week":
        return _week(args)
    if args.command == "snapshot":
        return _snapshot(args)
    if args.command == "patterns":
        return _patterns(args)
    if args.command == "prefs":
        return _prefs(args)
    return 1


def _today(args) -> int:
    prefs = config.with_overrides(min_lanes=args.min_lanes)
    date = args.date or config.today()
    now = None if (args.all_day or date != config.today()) else config.now().time()
    snapshot = client.fetch(start_date=date, days=1)
    render = report.render_html if args.html else report.render_text
    print(render(snapshot, date=date, now=now, min_lanes=prefs.min_lanes))
    return 0


def _week(args) -> int:
    prefs = config.with_overrides(window=args.window, min_lanes=args.min_lanes)
    # Only the first day can be half over, and only if it is actually today.
    now = None if (args.all_day or args.start > config.today()) else config.now()
    snapshot = client.fetch(start_date=args.start, days=args.days)
    render = report.render_week_html if args.html else report.render_week_text
    print(render(snapshot.days, prefs=prefs, now=now))
    return 0


def _snapshot(args) -> int:
    snapshot = client.fetch(days=args.days)
    written = store.save(snapshot)
    print(
        f"fetched {len(snapshot.days)} day-records, "
        f"wrote {written} new/changed to {store.DEFAULT_PATH}"
    )
    return 0


def _prefs(args) -> int:
    prefs = config.preferences()
    if args.timezone:
        print(prefs.timezone)
        return 0

    rows = {
        "timezone": prefs.timezone,
        "window": f"{_h(prefs.window_start)}-{_h(prefs.window_stop)}",
        "ideal": f"{_h(prefs.ideal_start)}-{_h(prefs.ideal_stop)}",
        "session": f"{prefs.session_minutes} min",
        "min lanes": str(prefs.min_lanes),
        "prefer end": prefs.prefer_end,
        "days": " ".join(d for d in WEEKDAY_NAMES if d in prefs.days),
    }
    print(config.PREFERENCES_PATH)
    print()
    for key, value in rows.items():
        print(f"  {key:<12} {value}")
    now = config.now()
    print(f"\n  it is {_h(now.time())} on {now:%A %-d %B} at the pool")
    return 0


def _patterns(args) -> int:
    days = []
    if args.source in ("live", "both"):
        days += client.fetch(days=client.MAX_DAYS_AHEAD).days
    if args.source in ("history", "both"):
        seen = {(d.end, d.date) for d in days}
        days += [d for d in store.load() if (d.end, d.date) not in seen]

    if not days:
        print("no data", file=sys.stderr)
        return 1

    # Today is partly elapsed, and the API reports past blocks as they were --
    # fine for a report, misleading when averaging weeks together.
    patterns = analyse.find_patterns(days, skip_dates={config.today()})
    if args.end:
        patterns = [p for p in patterns if p.end == args.end]
    if args.unnamed:
        patterns = analyse.unnamed(patterns)

    dates = sorted({d.date for d in days})
    print(f"{len(dates)} days observed, {dates[0]} to {dates[-1]}\n")

    current = None
    for pattern in patterns:
        key = (pattern.end, pattern.weekday)
        if key != current:
            current = key
            print(f"{pattern.end.upper()} - {pattern.weekday}")
        print(
            f"  {pattern.time_range():<18} {pattern.lanes_booked}/8 booked"
            f"  {pattern.frequency:<14} {pattern.who}"
        )
    if not patterns:
        print("every recurring booking is named in rules.toml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
