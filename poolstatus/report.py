"""Render a day's availability, for reading in a terminal or in an email."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from html import escape

from .classify import attribute, load_rules
from .hours import describe as describe_hours
from .hours import is_open
from .model import PoolDay, Slot, Snapshot, _h

# How many free lanes it takes before a block is worth swimming in.
COMFORTABLE = 3


@dataclass(slots=True)
class Band:
    """A run of consecutive blocks with the same availability and the same users."""

    start: dt.time
    stop: dt.time
    lanes_free: int
    lanes_total: int
    who: str
    open: bool

    def time_range(self) -> str:
        return f"{_h(self.start)}-{_h(self.stop)}"

    def availability(self) -> str:
        if not self.open:
            return "closed"
        if self.lanes_free == 0:
            return "booked out"
        return f"{self.lanes_free} of {self.lanes_total} lanes"


def bands(day: PoolDay, since: dt.time | None = None) -> list[Band]:
    """Collapse a day into runs of equal availability, with who has the rest."""
    rules = load_rules()
    rows = []
    for slot in day.slots:
        if since and slot.end <= since:
            continue
        open_now = is_open(day.date, slot)
        who = attribute(day.end, day.date, slot, rules).summary() if open_now else ""
        rows.append((slot, open_now, who))

    out: list[Band] = []
    for slot, open_now, who in rows:
        if (
            out
            and out[-1].stop == slot.start
            and out[-1].lanes_free == slot.lanes_free
            and out[-1].who == who
            and out[-1].open == open_now
        ):
            out[-1].stop = slot.end
            continue
        out.append(
            Band(
                start=slot.start,
                stop=slot.end,
                lanes_free=slot.lanes_free,
                lanes_total=slot.lanes_total,
                who=who,
                open=open_now,
            )
        )
    return out


def best_windows(day: PoolDay, min_lanes: int = COMFORTABLE, since: dt.time | None = None):
    """The stretches actually worth turning up for."""
    return [b for b in bands(day, since) if b.open and b.lanes_free >= min_lanes]


def render_text(
    snapshot: Snapshot,
    date: dt.date | None = None,
    now: dt.time | None = None,
    min_lanes: int = COMFORTABLE,
) -> str:
    date = date or dt.date.today()
    days = snapshot.for_date(date)
    if not days:
        return _no_data(date) + "\n"

    lines = [
        f"UNSW pool lanes - {date:%A %-d %B}",
        f"Centre open {describe_hours(date)}"
        + (f", from {_h(now)} onwards" if now else ""),
        "",
    ]

    if now:
        current = []
        for end, day in sorted(days.items()):
            slot = _slot_covering(day, now)
            if slot and is_open(date, slot):
                current.append(f"{day.calendar_name}: {slot.lanes_free}/{slot.lanes_total} free")
        if current:
            lines += ["Right now - " + "  |  ".join(current), ""]

    for end, day in sorted(days.items()):
        lines.append(day.calendar_name.upper())
        rows = bands(day, since=now)
        if not rows:
            lines += ["  nothing left today", ""]
            continue
        width = max(len(b.time_range()) for b in rows)
        for band in rows:
            marker = " " if not band.open else ("+" if band.lanes_free >= min_lanes else " ")
            detail = f"   {band.who}" if band.who else ""
            lines.append(
                f" {marker} {band.time_range():<{width}}  {band.availability()}{detail}"
            )

        good = [b for b in rows if b.open and b.lanes_free >= min_lanes]
        if not good:
            lines.append(f"   nothing with {min_lanes}+ lanes free")
        elif len(good) < len([b for b in rows if b.open]):
            # Only worth a summary when something is actually contested.
            longest = sorted(good, key=_duration, reverse=True)[:3]
            longest.sort(key=lambda b: b.start)
            lines.append(
                "   most room: "
                + ", ".join(f"{b.time_range()} ({b.lanes_free})" for b in longest)
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_html(
    snapshot: Snapshot,
    date: dt.date | None = None,
    now: dt.time | None = None,
    min_lanes: int = COMFORTABLE,
) -> str:
    """Self-contained HTML with inline styles, safe to drop into an email body."""
    date = date or dt.date.today()
    days = snapshot.for_date(date)
    if not days:
        return f"<p>{escape(_no_data(date))}</p>"

    head = (
        '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
        'font-size:15px;color:#1a1a1a;max-width:640px">'
        f'<h2 style="margin:0 0 4px;font-size:19px">UNSW pool lanes'
        f'<span style="color:#666;font-weight:400"> &middot; {escape(f"{date:%A %-d %B}")}</span></h2>'
        f'<p style="margin:0 0 18px;color:#666;font-size:13px">Centre open {escape(describe_hours(date))}'
        + (f", from {escape(_h(now))} onwards" if now else "")
        + "</p>"
    )

    sections = []
    for end, day in sorted(days.items()):
        rows = bands(day, since=now)
        cells = []
        for band in rows:
            if not band.open:
                bg, fg = "#f4f4f5", "#9a9a9a"
            elif band.lanes_free == 0:
                bg, fg = "#fdeceb", "#a3312a"
            elif band.lanes_free >= min_lanes:
                bg, fg = "#eaf6ec", "#1f6b32"
            else:
                bg, fg = "#fdf6e3", "#8a6a12"
            who = (
                f'<span style="color:#777;font-size:13px"> &middot; {escape(band.who)}</span>'
                if band.who
                else ""
            )
            cells.append(
                f'<tr style="background:{bg}">'
                f'<td style="padding:6px 10px;white-space:nowrap;color:{fg};'
                f'font-variant-numeric:tabular-nums">{escape(band.time_range())}</td>'
                f'<td style="padding:6px 10px;color:{fg}">'
                f"<strong>{escape(band.availability())}</strong>{who}</td></tr>"
            )
        body = (
            "".join(cells)
            or '<tr><td style="padding:6px 10px;color:#777">nothing left today</td></tr>'
        )
        sections.append(
            f'<h3 style="margin:18px 0 6px;font-size:15px">{escape(day.calendar_name)}</h3>'
            '<table cellpadding="0" cellspacing="0" border="0" '
            'style="border-collapse:collapse;width:100%">'
            f"{body}</table>"
        )

    return head + "".join(sections) + "</div>"


def render_week_text(days: list[PoolDay], min_lanes: int = COMFORTABLE) -> str:
    """A compact grid: one row per day, one character per half hour."""
    from .store import grid_times

    times = grid_times()
    # Two half-hour columns per hour, so a right-aligned hour label fits exactly.
    header = "".join(f"{t.hour:2d}" for t in times if t.minute == 0)

    by_end: dict[str, list[PoolDay]] = {}
    for day in days:
        by_end.setdefault(day.end, []).append(day)

    lines = []
    for end, end_days in sorted(by_end.items()):
        lines += [end_days[0].calendar_name.upper(), f"{'':<15}{header}"]
        for day in sorted(end_days, key=lambda d: d.date):
            by_start = {s.start: s for s in day.slots}
            row = []
            for t in times:
                slot = by_start.get(t)
                if slot is None or not is_open(day.date, slot):
                    row.append(" ")
                elif slot.lanes_free == 0:
                    row.append("#")
                else:
                    row.append(str(slot.lanes_free))
            lines.append(f"{day.date:%a %-d %b}".ljust(15) + "".join(row))
        lines.append("")
    lines.append("digit = lanes free    # = booked out    blank = closed")
    return "\n".join(lines) + "\n"


def _no_data(date: dt.date) -> str:
    """The API only ever knows about today and roughly the next four weeks."""
    today = dt.date.today()
    if date < today:
        why = "the calendar clamps past dates to today"
    elif (date - today).days > 28:
        why = "bookings are only published about four weeks ahead"
    else:
        why = "the calendar returned nothing for that day"
    return f"No lane data for {date:%A %-d %B} - {why}."


def _duration(band: Band) -> int:
    return (band.stop.hour * 60 + band.stop.minute) - (
        band.start.hour * 60 + band.start.minute
    )


def _slot_covering(day: PoolDay, when: dt.time) -> Slot | None:
    return next((s for s in day.slots if s.start <= when < s.end), None)
