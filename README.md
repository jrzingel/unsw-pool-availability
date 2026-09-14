# poolstatus

Lane availability for the UNSW Fitness & Aquatic Centre pool, so you know before
you walk down there.

```
uv run poolstatus week           # the week ahead, and when to go -- this is the email
uv run poolstatus week --html    # same thing as an HTML email body
uv run poolstatus today          # what is free for the rest of today, and who has the rest
uv run poolstatus prefs          # the swim preferences currently in force
uv run poolstatus snapshot       # append today's picture to the local history
uv run poolstatus patterns       # recurring bookings, and which ones are still unnamed
```

Every date and time is the pool's, in `Australia/Sydney`, whatever clock the
machine running it happens to be set to.

## Where the numbers come from

The lane-availability page is an empty Vue shell — there is nothing in the HTML
to scrape. The numbers come from a PerfectGym JSON endpoint that needs no login:

```
GET https://unswfac.perfectgym.com.au/ClientPortal2/api
      /Calendars/ClubZoneOccupancyCalendar/GetCalendar
      ?calendarId=<id>&startDate=YYYY-MM-DD&daysPerPage=<n>
```

`calendarId` is `07145b7c1` for the 25m deep end and `b702872a2` for the shallow
end — the two halves of the split 50m pool, eight lanes each. Each response is a
grid of half-hour blocks with `totalCountOfOccupancyAvailability` (lanes free)
out of `numberOfFacilities` (8).

Four things worth knowing about it:

- **No history.** Any `startDate` in the past is silently clamped to today, so
  yesterday is gone the moment it passes. `poolstatus snapshot` exists to build
  a record locally — run it from cron alongside the email.
- **`daysPerPage` truncates the grid.** The response is trimmed to the span of
  non-empty blocks across the whole page, so asking for one day drops real
  early-morning and late-evening blocks. Asking for a week or more always
  returns the full 6:00am–9:30pm grid; the client always asks for at least
  seven days and trims afterwards.
- **`startDate` is snapped back to Monday.** The page always begins at the
  start of the week the date falls in and runs `daysPerPage` days from there,
  so seven days asked for from a Wednesday come back two days short. The client
  pays for the days at the front of the week and trims them off.
- **Closed looks exactly like booked out.** Both report zero lanes free. The
  centre's hours (Mon–Fri 6am–10pm, Sat/Sun 7am–7pm, pool closes 15 min earlier)
  live in `hours.py`, which is what stops the weekend 6–7am and 7–9:30pm bands
  reading as enormous phantom bookings.

## Who books the lanes

The API never says. `rules.toml` attaches names to recurring blocks, and is
meant to be edited by hand — that is where your local knowledge goes. Anything
booked that no rule claims is reported as *unattributed*:

```
uv run poolstatus patterns --unnamed
```

Rules seeded from what is published and what the data shows, measured over
2026-09-05 to 2026-10-01 (four weeks, school term):

**Confirmed** — matches a published timetable

| When | Where | Who |
|---|---|---|
| Mon/Wed/Fri 6:00–7:30am | deep, all 8 | Swim squads: Gold/Platinum/Adult 5:30am, Bronze/Silver 6:15am |
| Sat 7:00–9:00am | deep, all 8 | Swim squads, all four levels start 7am |
| Weekdays from 3:45pm | deep, ~6 | Swim squads: Pre/Bronze/Platinum 3:45pm, Silver/Gold 4:30pm, Teen 4:45pm |
| Tue/Thu/Fri 10:45am | shallow, ~3 | Aqua class (45 min, on the group fitness timetable) |

**Inferred** — clear in the data, name is a guess

| When | Where | Who |
|---|---|---|
| Fri 7:30–9:00am | deep, all 8 | School booking — holds 2 weeks in 3, which fits your "sometimes schools book till 9am" |
| Mon–Fri 4:00–8:00/9:00pm | deep, all 8 | Squads only explain ~6 lanes; the rest is standing club hire, water polo shaped |
| Weekdays 3:30–7:00pm | shallow, 3–4 | Learn to Swim |
| Sat/Sun 8:30am–12pm | shallow, 3–4 | Learn to Swim |
| Mon–Wed 2:00–3:00pm | deep, all 8 | Whole deep end vanishes for an hour, roughly fortnightly — schools |

## The practical upshot

- **The deep end is the problem.** It is booked out every weekday from 4pm
  (until 8pm Wed/Fri, 9pm Mon/Tue/Thu), every Mon/Wed/Fri before 7:30am, and
  Friday mornings usually until 9am.
- **The shallow end never dropped below two free lanes** during opening hours
  across the whole four-week window — and below three only four times. If you
  just want to swim, go there.
- Deep end, three or more lanes free (school term):

  | | |
  |---|---|
  | Mon | 7:30am–2pm, 3–4pm, 9–9:30pm |
  | Tue | 6–7:30am, 8:30am–2pm, 3–4pm, 9–9:30pm |
  | Wed | 7:30am–2pm, 3–4pm, 8–9:30pm |
  | Thu | **6am–4pm**, 9–9:30pm |
  | Fri | 9am–4pm, 8–9:30pm |
  | Sat | 9am–7pm |
  | Sun | 7am–7pm |

  The 2–3pm hole on Mon/Tue/Wed is the intermittent midday block. Thursday
  morning is the one weekday the deep end is yours.

## When to go

The week report opens with one answer — the best swim in the next seven days —
before the timetable it came from:

```
BEST SWIM     Thursday 17 September, 8am-9am, 25M Deep End - 8 lanes free
           or Friday 18 September, 8am-9am, 25M Deep End - 8 lanes free
           or Tuesday 15 September, 8am-9am, 25M Shallow End - 8 lanes free
```

A candidate is a run of blocks inside your window, long enough for a swim, open,
and with enough lanes free the whole way through. They rank on the lanes you are
*guaranteed* (a window that dips to two lanes is a two-lane window), then on how
much of it lands in the hour you actually want, then on which half of the pool.
One per day, so the runners-up are alternatives rather than the same morning
sliced five ways. If nothing clears the bar all week it says so, and still names
the closest thing.

What counts as good is yours, in `poolstatus/preferences.toml` — the second
hand-edited file, alongside `rules.toml`:

```toml
timezone = "Australia/Sydney"
window = "8:00-10:00"       # when you would swim
ideal  = "8:00-9:00"        # when you would rather
session_minutes = 60
min_lanes = 3               # fewer than this is not worth the walk
prefer_end = "deep"         # which half wins a tie
days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
```

`uv run poolstatus prefs` prints what is in force, and the local time it
resolves to. `--window 6:00-9:00` and `--min-lanes 4` override the file for one
run without editing it.

## Emailing it

`send_report.sh` builds the week report and posts it to Mailgun. One-time setup:

```sh
cp poolstatus.env.example poolstatus.env
chmod 600 poolstatus.env      # the script refuses to run if others can read it
$EDITOR poolstatus.env        # MAILGUN_API_KEY, MAILGUN_DOMAIN, MAIL_FROM, MAIL_TO
./send_report.sh              # check it arrives
```

One email a week, Sunday evening, covering Monday to Sunday. Then in
`crontab -e`:

```
TZ=Australia/Sydney
30 18 * * 0 /home/james/projects/poolstatus/send_report.sh >> /home/james/projects/poolstatus/cron.log 2>&1
15  6 * * * /home/james/projects/poolstatus/.venv/bin/poolstatus snapshot >> /home/james/projects/poolstatus/cron.log 2>&1
```

**The server is on UTC and the pool is not.** Two separate things have to be
fixed for that, and only one of them is cron's:

- *What the report says.* Handled — the report is rendered in the timezone from
  `preferences.toml` no matter what the host clock says, and `send_report.sh`
  asks the package for that zone and sets its own `TZ` from it, so the log
  stamps and the subject line agree with the body.
- *When cron fires.* Not something the script can fix from the inside. The
  `TZ=Australia/Sydney` line above works on Debian/Ubuntu cron and cronie, and
  it handles daylight saving. If yours ignores it, wake the script hourly and
  let it pick its own moment instead:

  ```
  17 * * * * SEND_AT="Sun 18" /home/james/projects/poolstatus/send_report.sh >> .../cron.log 2>&1
  ```

  `SEND_AT` is a local weekday and hour; any other hour the script exits
  quietly, before it touches the network.

The second cron line keeps the history dense. The weekly email takes a snapshot
too, but once a week is a thin record to mine for patterns, and a snapshot only
appends when the picture actually changed.

`poolstatus.env` and `cron.log` are gitignored, along with `data/`.

Set `POOLSTATUS_ARGS` in the env file to change what is sent — it defaults to
`--from tomorrow` (Sunday evening, so the week starts Monday). `--from today`
to include the rest of today, `--days 14` for a fortnight, `--min-lanes 4` to
raise the bar, `--window 6:00-9:00` for one-off early starts.

A few details, since this runs unattended:

- The API key is passed to curl through a config file, never on the command
  line, so it does not show up in `ps`.
- Building the report retries three times with a backoff — one network hiccup
  should not cost the week's email.
- The subject line is lifted from the report itself (`UNSW pool lanes · Mon 15
  Sep to Sun 21 Sep`), so it cannot drift from what is in the body.
- It works under cron's stripped environment (no `PATH`, no locale); it calls
  `.venv/bin/poolstatus` by absolute path rather than going through `uv`.

To send from your own code instead:

```python
from poolstatus import client, config
from poolstatus.report import render_week_html, render_week_text

snapshot = client.fetch(start_date=config.today(), days=7)
html = render_week_html(snapshot.days, now=config.now())
text = render_week_text(snapshot.days, now=config.now())
```

Pass `now=None` to keep today's elapsed blocks, and `prefs=` to override
`preferences.toml`. The single-day `render_html` / `render_text` still take a
`Snapshot` and a `date`.

## Layout

| File | What it does |
|---|---|
| `client.py` | the JSON API, and the quirks above |
| `model.py` | `Slot` / `PoolDay` / `Snapshot` |
| `hours.py` | opening hours, so closed ≠ booked out |
| `rules.toml` | **who books what — edit this** |
| `preferences.toml` | **when you like to swim — edit this** |
| `config.py` | reads the preferences; the pool's clock, not the host's |
| `classify.py` | matches blocks against the rules |
| `recommend.py` | ranks the week's windows and picks one |
| `analyse.py` | finds the recurring weekly shape |
| `store.py` | appends observations to `data/history.jsonl` |
| `report.py` | text and HTML, for a day and for the week |
| `cli.py` | the commands above |
| `send_report.sh` | builds the report and posts it to Mailgun; for cron |
| `poolstatus.env.example` | template for the gitignored `poolstatus.env` |

`check_availability.py` is the original scratch note with the links; everything
in it now lives in `client.py`.
