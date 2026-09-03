"""Command line entry point.

    poolstatus today            what is free today, and who has the rest
    poolstatus today --html     same, as HTML for an email body
    poolstatus week             a 7-day grid for both ends
    poolstatus snapshot         fetch and append to the local history
    poolstatus patterns         recurring bookings, and which are still unnamed
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from . import analyse, client, report, store
from .model import ENDS


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
    today.add_argument("--min-lanes", type=int, default=report.COMFORTABLE)

    week = sub.add_parser("week", help="a 7-day grid")
    week.add_argument("--days", type=int, default=7)
    week.add_argument("--min-lanes", type=int, default=report.COMFORTABLE)

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

    args = parser.parse_args(argv)

    if args.command == "today":
        return _today(args)
    if args.command == "week":
        return _week(args)
    if args.command == "snapshot":
        return _snapshot(args)
    if args.command == "patterns":
        return _patterns(args)
    return 1


def _today(args) -> int:
    date = args.date or dt.date.today()
    now = None if (args.all_day or date != dt.date.today()) else dt.datetime.now().time()
    snapshot = client.fetch(start_date=date, days=1)
    render = report.render_html if args.html else report.render_text
    print(render(snapshot, date=date, now=now, min_lanes=args.min_lanes))
    return 0


def _week(args) -> int:
    snapshot = client.fetch(days=args.days)
    print(report.render_week_text(snapshot.days, min_lanes=args.min_lanes))
    return 0


def _snapshot(args) -> int:
    snapshot = client.fetch(days=args.days)
    written = store.save(snapshot)
    print(
        f"fetched {len(snapshot.days)} day-records, "
        f"wrote {written} new/changed to {store.DEFAULT_PATH}"
    )
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
    patterns = analyse.find_patterns(days, skip_dates={dt.date.today()})
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
