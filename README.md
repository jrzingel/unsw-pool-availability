# poolstatus

Lane availability for the UNSW Fitness & Aquatic Centre pool, so you know before
you walk down there.

```
uv run poolstatus today          # what is free for the rest of today, and who has the rest
uv run poolstatus today --html   # same thing as an HTML email body
uv run poolstatus week           # 7-day grid, both ends
uv run poolstatus snapshot       # append today's picture to the local history
uv run poolstatus patterns       # recurring bookings, and which ones are still unnamed
```

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

Three things worth knowing about it:

- **No history.** Any `startDate` in the past is silently clamped to today, so
  yesterday is gone the moment it passes. `poolstatus snapshot` exists to build
  a record locally — run it from cron alongside the email.
- **`daysPerPage` truncates the grid.** The response is trimmed to the span of
  non-empty blocks across the whole page, so asking for one day drops real
  early-morning and late-evening blocks. Asking for a week or more always
  returns the full 6:00am–9:30pm grid; the client always asks for at least
  seven days and trims afterwards.
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

## Emailing it

`send_report.sh` builds the report and posts it to Mailgun. One-time setup:

```sh
cp poolstatus.env.example poolstatus.env
chmod 600 poolstatus.env      # the script refuses to run if others can read it
$EDITOR poolstatus.env        # MAILGUN_API_KEY, MAILGUN_DOMAIN, MAIL_FROM, MAIL_TO
./send_report.sh              # check it arrives
```

Then in `crontab -e`:

```
30 6 * * * /home/james/projects/poolstatus/send_report.sh >> /home/james/projects/poolstatus/cron.log 2>&1
```

`poolstatus.env` and `cron.log` are gitignored, along with `data/`.

The email covers the rest of the day from the time it is sent, so a 6:30am cron
gives you the whole day. Set `POOLSTATUS_ARGS` in the env file to change that —
`--all-day` to always show the full day, `--min-lanes 4` to raise the bar for
what counts as worth turning up for.

Each run also does a `poolstatus snapshot`, so the history builds up on its own.
That failing does not stop the email.

A few details, since this runs unattended:

- The API key is passed to curl through a config file, never on the command
  line, so it does not show up in `ps`.
- Building the report retries three times with a backoff — one 6am network
  hiccup should not cost the day's email.
- It works under cron's stripped environment (no `PATH`, no locale); it calls
  `.venv/bin/poolstatus` by absolute path rather than going through `uv`.

To send from your own code instead:

```python
import datetime as dt
from poolstatus import client
from poolstatus.report import render_html, render_text

snapshot = client.fetch(days=1)
html = render_html(snapshot, now=dt.datetime.now().time())
text = render_text(snapshot, now=dt.datetime.now().time())
```

Pass `now=None` for the whole day rather than just what is left of it.

## Layout

| File | What it does |
|---|---|
| `client.py` | the JSON API, and the two quirks above |
| `model.py` | `Slot` / `PoolDay` / `Snapshot` |
| `hours.py` | opening hours, so closed ≠ booked out |
| `rules.toml` | **who books what — edit this** |
| `classify.py` | matches blocks against the rules |
| `analyse.py` | finds the recurring weekly shape |
| `store.py` | appends observations to `data/history.jsonl` |
| `report.py` | text and HTML rendering |
| `cli.py` | the commands above |
| `send_report.sh` | builds the report and posts it to Mailgun; for cron |
| `poolstatus.env.example` | template for the gitignored `poolstatus.env` |

`check_availability.py` is the original scratch note with the links; everything
in it now lives in `client.py`.
