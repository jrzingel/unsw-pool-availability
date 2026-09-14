"""Render availability -- a day, or the week ahead -- for a terminal or an email."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from html import escape

from . import config, recommend
from .classify import attribute, load_rules
from .hours import describe as describe_hours
from .hours import is_open
from .model import PoolDay, Slot, Snapshot, _h

# How many free lanes it takes before a block is worth swimming in, when
# nothing says otherwise.  preferences.toml is the real answer.
COMFORTABLE = 3

# One background/foreground pair per way a block can be, shared by the day and
# week renderers so the two read as the same report.
PALETTE = {
    "none": ("#f4f4f5", "#9a9a9a"),
    "closed": ("#f4f4f5", "#9a9a9a"),
    "full": ("#fdeceb", "#a3312a"),
    "tight": ("#fdf6e3", "#8a6a12"),
    "free": ("#eaf6ec", "#1f6b32"),
}


def category(open_now: bool, lanes_free: int | None, min_lanes: int) -> str:
    """How a block should read: no data, closed, booked out, tight, or free."""
    if lanes_free is None:
        return "none"
    if not open_now:
        return "closed"
    if lanes_free == 0:
        return "full"
    return "free" if lanes_free >= min_lanes else "tight"


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
    date = date or config.today()
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
    date = date or config.today()
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
            bg, fg = PALETTE[category(band.open, band.lanes_free, min_lanes)]
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


@dataclass(frozen=True, slots=True)
class Cell:
    """One half of the pool for one band of the week timetable.

    Unlike a day's `Band`, a cell holds a *range* of free lanes.  Over a week
    the exact count wobbles block to block, and collapsing on the exact number
    is what made the old week grid unreadable; collapsing on what the number
    means -- closed, booked out, tight, free -- is what makes this a timetable.
    """

    category: str
    lanes_low: int
    lanes_high: int
    lanes_total: int
    who: str

    def availability(self) -> str:
        if self.category == "none":
            return ""
        if self.category == "closed":
            return "closed"
        if self.category == "full":
            return "booked out"
        if self.lanes_low == self.lanes_high:
            return f"{self.lanes_low} free"
        return f"{self.lanes_low}-{self.lanes_high} free"

    def same_as(self, other: Cell) -> bool:
        return self.category == other.category and self.who == other.who

    def widened(self, other: Cell) -> Cell:
        return replace(
            self,
            lanes_low=min(self.lanes_low, other.lanes_low),
            lanes_high=max(self.lanes_high, other.lanes_high),
        )


@dataclass(slots=True)
class WeekRow:
    """One time band, with both halves of the pool side by side."""

    start: dt.time
    stop: dt.time
    cells: dict[str, Cell]

    def time_range(self) -> str:
        return f"{_h(self.start)}-{_h(self.stop)}"


def week_rows(
    day_by_end: dict[str, PoolDay],
    min_lanes: int = COMFORTABLE,
    since: dt.time | None = None,
) -> list[WeekRow]:
    """One day, both ends, collapsed into bands that mean the same thing."""
    rules = load_rules()
    ends = sorted(day_by_end)
    starts = sorted(
        {
            slot.start
            for day in day_by_end.values()
            for slot in day.slots
            if not (since and slot.end <= since)
        }
    )

    rows: list[WeekRow] = []
    for start in starts:
        cells: dict[str, Cell] = {}
        stop = None
        for end in ends:
            day = day_by_end[end]
            slot = day.slot_at(start)
            if slot is not None:
                stop = slot.end
            cells[end] = _cell(day, slot, min_lanes, rules)
        if stop is None:
            continue

        previous = rows[-1] if rows else None
        if previous and previous.stop == start and all(
            previous.cells[end].same_as(cells[end]) for end in ends
        ):
            previous.stop = stop
            previous.cells = {
                end: previous.cells[end].widened(cells[end]) for end in ends
            }
            continue
        rows.append(WeekRow(start=start, stop=stop, cells=cells))

    # The day header already says when the centre is open; a "closed" row top
    # and bottom of every weekend day is just padding.
    shut = {"closed", "none"}
    while rows and all(cell.category in shut for cell in rows[0].cells.values()):
        rows.pop(0)
    while rows and all(cell.category in shut for cell in rows[-1].cells.values()):
        rows.pop()
    return rows


def render_week_text(
    days: list[PoolDay],
    prefs: config.Preferences | None = None,
    now: dt.datetime | None = None,
) -> str:
    """The week ahead as one timetable per day, led by where to actually go."""
    prefs = prefs or config.preferences()
    grouped = _by_date(days, now)
    if not grouped:
        return "No lane data for the week ahead.\n"

    ends = sorted({d.end for d in days})
    names = {d.end: d.calendar_name for d in days}
    timetables = [
        (date, by_end, week_rows(by_end, prefs.min_lanes, since=_since(date, now)))
        for date, by_end in grouped
    ]

    time_width = max(
        (len(row.time_range()) for _, _, rows in timetables for row in rows), default=10
    )
    cell_width = max(
        (
            len(_cell_text(row.cells[end]))
            for _, _, rows in timetables
            for row in rows
            for end in ends[:-1]
        ),
        default=20,
    )
    cell_width = max(cell_width, max((len(names[e]) for e in ends[:-1]), default=0))

    lines = [
        "UNSW pool lanes - the week ahead",
        f"{grouped[0][0]:%a %-d %b} to {grouped[-1][0]:%a %-d %b}",
        "",
    ]
    lines += _pick_lines(recommend.best(days, prefs, now=now))
    lines += ["", " " * (time_width + 4) + "  ".join(
        f"{names[end]:<{cell_width}}" if index < len(ends) - 1 else names[end]
        for index, end in enumerate(ends)
    )]

    for date, _, rows in timetables:
        since = _since(date, now)
        lines.append("")
        lines.append(
            f"{date:%A %-d %B}".upper()
            + f"   open {describe_hours(date)}"
            + (f", from {_h(since)} onwards" if since else "")
        )
        if not rows:
            lines.append("   nothing left today")
            continue
        for row in rows:
            marker = ">" if prefs.in_window(row.start, row.stop) else " "
            cells = "  ".join(
                f"{_cell_text(row.cells[end]):<{cell_width}}"
                if index < len(ends) - 1
                else _cell_text(row.cells[end])
                for index, end in enumerate(ends)
            )
            lines.append(
                f" {marker} {row.time_range():<{time_width}}  {cells}".rstrip()
            )

    lines += [
        "",
        (
            f"> marks your swim window, {_h(prefs.window_start)}-"
            f"{_h(prefs.window_stop)}.  Lane counts are the range across the band."
        ),
        (
            "Edit preferences.toml to change the window, the session length, or"
            " how many free lanes count."
        ),
    ]
    return "\n".join(lines) + "\n"


def render_week_html(
    days: list[PoolDay],
    prefs: config.Preferences | None = None,
    now: dt.datetime | None = None,
) -> str:
    """The same week, as a self-contained email body."""
    prefs = prefs or config.preferences()
    grouped = _by_date(days, now)
    if not grouped:
        return "<p>No lane data for the week ahead.</p>"

    ends = sorted({d.end for d in days})
    names = {d.end: d.calendar_name for d in days}

    out = [
        (
            '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
            'font-size:15px;color:#1a1a1a;max-width:720px">'
            '<h2 style="margin:0 0 4px;font-size:19px">UNSW pool lanes'
            '<span style="color:#666;font-weight:400"> &middot; the week ahead'
            "</span></h2>"
            f'<p style="margin:0 0 16px;color:#666;font-size:13px">'
            f'{escape(f"{grouped[0][0]:%a %-d %b}")} to '
            f'{escape(f"{grouped[-1][0]:%a %-d %b}")}</p>'
        ),
        _pick_html(recommend.best(days, prefs, now=now)),
    ]

    for date, by_end in grouped:
        since = _since(date, now)
        rows = week_rows(by_end, prefs.min_lanes, since=since)
        header = "".join(
            f'<th style="padding:4px 10px;text-align:left;font-size:12px;color:#888;'
            f'font-weight:600;text-transform:uppercase;letter-spacing:.04em">'
            f"{escape(names[end])}</th>"
            for end in ends
        )
        body = []
        for row in rows:
            wanted = prefs.in_window(row.start, row.stop)
            accent = "border-left:3px solid #1f6b32;" if wanted else "border-left:3px solid transparent;"
            weight = "600" if wanted else "400"
            cells = "".join(
                _cell_html(row.cells[end]) for end in ends
            )
            body.append(
                f'<tr><td style="{accent}padding:6px 10px;white-space:nowrap;'
                f'font-weight:{weight};font-variant-numeric:tabular-nums">'
                f"{escape(row.time_range())}</td>{cells}</tr>"
            )
        if not body:
            body.append(
                f'<tr><td colspan="{len(ends) + 1}" style="padding:6px 10px;color:#777">'
                "nothing left today</td></tr>"
            )
        out.append(
            f'<h3 style="margin:20px 0 6px;font-size:15px">{escape(f"{date:%A %-d %B}")}'
            f'<span style="color:#888;font-weight:400;font-size:13px"> &middot; open '
            f"{escape(describe_hours(date))}"
            + (f", from {escape(_h(since))} onwards" if since else "")
            + "</span></h3>"
            '<table cellpadding="0" cellspacing="0" border="0" '
            'style="border-collapse:collapse;width:100%">'
            f'<tr><th style="padding:4px 10px;text-align:left"></th>{header}</tr>'
            f'{"".join(body)}</table>'
        )

    out.append(
        '<p style="margin:22px 0 0;color:#888;font-size:12px">'
        f"The green edge marks your swim window, {escape(_h(prefs.window_start))}-"
        f"{escape(_h(prefs.window_stop))}. Lane counts are the range across the band. "
        "Edit <code>preferences.toml</code> to change the window, the session "
        "length, or how many free lanes count.</p></div>"
    )
    return "".join(out)


def _cell(day: PoolDay, slot: Slot | None, min_lanes: int, rules) -> Cell:
    if slot is None:
        return Cell(category="none", lanes_low=0, lanes_high=0, lanes_total=0, who="")
    open_now = is_open(day.date, slot)
    return Cell(
        category=category(open_now, slot.lanes_free, min_lanes),
        lanes_low=slot.lanes_free,
        lanes_high=slot.lanes_free,
        lanes_total=slot.lanes_total,
        who=attribute(day.end, day.date, slot, rules).named() if open_now else "",
    )


def _cell_text(cell: Cell) -> str:
    text = cell.availability()
    if cell.who:
        text += f"  {_clip(cell.who, 36)}"
    return text


def _cell_html(cell: Cell) -> str:
    bg, fg = PALETTE[cell.category]
    who = (
        f'<span style="color:#777;font-size:13px"> &middot; {escape(cell.who)}</span>'
        if cell.who
        else ""
    )
    return (
        f'<td style="background:{bg};color:{fg};padding:6px 10px">'
        f"<strong>{escape(cell.availability())}</strong>{who}</td>"
    )


def _pick_lines(pick: recommend.Recommendation) -> list[str]:
    """The recommendation, as the first thing you read."""
    prefs = pick.prefs
    if not pick.best:
        return [
            (
                f"NO SWIM FITS  nothing open for {prefs.session_minutes} min "
                f"between {_h(prefs.window_start)} and {_h(prefs.window_stop)} "
                "this week."
            ),
            f"              {prefs.describe()} - edit preferences.toml.",
        ]

    label = "CLOSEST" if pick.relaxed else "BEST SWIM"
    lines = [f"{label:<13} {pick.best.describe()}"]
    for other in pick.picks[1:]:
        lines.append(f"{'or':>13} {other.describe()}")
    if pick.relaxed:
        lines.append(f"{'':13} nothing all week had {prefs.min_lanes}+ lanes free.")
    lines.append(f"{'':13} wanted: {prefs.describe()} (preferences.toml)")
    return lines


def _pick_html(pick: recommend.Recommendation) -> str:
    prefs = pick.prefs
    if not pick.best:
        return (
            '<div style="border-left:4px solid #8a6a12;background:#fdf6e3;'
            'padding:12px 16px;margin:0 0 20px;color:#5c4a12">'
            '<div style="font-size:12px;letter-spacing:.06em;text-transform:uppercase;'
            'font-weight:600">No swim fits</div>'
            f'<div style="font-size:15px;margin-top:4px">Nothing open for '
            f"{prefs.session_minutes} min between {escape(_h(prefs.window_start))} and "
            f"{escape(_h(prefs.window_stop))} this week.</div>"
            f'<div style="font-size:12px;margin-top:8px;opacity:.8">Wanted '
            f"{escape(prefs.describe())} &middot; edit preferences.toml</div></div>"
        )

    edge, bg, ink, faint = (
        ("#8a6a12", "#fdf6e3", "#5c4a12", "#7a6a3a")
        if pick.relaxed
        else ("#1f6b32", "#eaf6ec", "#14461f", "#4a6b52")
    )
    best = pick.best
    also = " &nbsp;&middot;&nbsp; ".join(
        f"{escape(f'{other.date:%a %-d %b}')} {escape(other.time_range())}, "
        f"{escape(other.end)} ({other.lanes_low})"
        for other in pick.picks[1:]
    )
    return (
        f'<div style="border-left:4px solid {edge};background:{bg};padding:12px 16px;'
        f'margin:0 0 20px;color:{ink}">'
        f'<div style="font-size:12px;letter-spacing:.06em;text-transform:uppercase;'
        f'font-weight:600;color:{edge}">'
        + ("Closest thing to a swim" if pick.relaxed else "Best swim this week")
        + "</div>"
        f'<div style="font-size:18px;font-weight:600;margin:4px 0 2px">'
        f'{escape(f"{best.date:%A %-d %B}")}, {escape(best.time_range())}</div>'
        f'<div style="font-size:14px">{escape(best.calendar_name)} &middot; '
        f"{escape(best.lanes())}</div>"
        + (
            f'<div style="font-size:13px;color:{faint};margin-top:8px">Also good: {also}</div>'
            if also
            else ""
        )
        + (
            f'<div style="font-size:13px;color:{faint};margin-top:8px">Nothing all week '
            f"had {prefs.min_lanes}+ lanes free in your window.</div>"
            if pick.relaxed
            else ""
        )
        + f'<div style="font-size:12px;color:{faint};margin-top:8px">Wanted '
        f"{escape(prefs.describe())} &middot; edit preferences.toml</div></div>"
    )


def _by_date(
    days: list[PoolDay], now: dt.datetime | None
) -> list[tuple[dt.date, dict[str, PoolDay]]]:
    """Group into calendar days, dropping any that are already over."""
    by_date: dict[dt.date, dict[str, PoolDay]] = {}
    for day in days:
        if not day.slots:
            continue
        if now and day.date < now.date():
            continue
        by_date.setdefault(day.date, {})[day.end] = day

    out = []
    for date in sorted(by_date):
        since = _since(date, now)
        if since and all(
            slot.end <= since for day in by_date[date].values() for slot in day.slots
        ):
            continue  # today is done; the week starts tomorrow
        out.append((date, by_date[date]))
    return out


def _since(date: dt.date, now: dt.datetime | None) -> dt.time | None:
    return now.time() if now and now.date() == date else None


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 3].rstrip() + "..."


def _no_data(date: dt.date) -> str:
    """The API only ever knows about today and roughly the next four weeks."""
    today = config.today()
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
