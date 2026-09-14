#!/usr/bin/env bash
#
# Email the week ahead via Mailgun.  Meant for cron:
#
#   # Sunday evening, Sydney time, on a host whose cron understands TZ:
#   TZ=Australia/Sydney
#   30 18 * * 0 /home/james/projects/poolstatus/send_report.sh >> .../cron.log 2>&1
#
#   # ...or, on a UTC host whose cron does not: wake hourly and let the script
#   # decide, which also survives daylight saving:
#   17 * * * * SEND_AT="Sun 18" /home/james/projects/poolstatus/send_report.sh >> .../cron.log 2>&1
#
# Either way the report itself is rendered in the pool's timezone, not the
# host's -- see preferences.toml.
#
# Secrets live in poolstatus.env next to this script (gitignored) -- copy
# poolstatus.env.example and fill it in:
#
#   cp poolstatus.env.example poolstatus.env && chmod 600 poolstatus.env
#
# Also appends today's picture to data/history.jsonl, since the calendar API
# cannot be asked about the past -- the only way to accumulate history is to
# keep looking.  A weekly email is a thin record, so there is a daily snapshot
# line in the README for that.

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
env_file="${POOLSTATUS_ENV:-$script_dir/poolstatus.env}"
poolstatus_bin="$script_dir/.venv/bin/poolstatus"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# --- config ----------------------------------------------------------------

[[ -f $env_file ]] || die "no config at $env_file (copy poolstatus.env.example)"

# Refuse to read secrets that anyone else on the box can read.
perms=$(stat -c '%a' "$env_file")
if (( 8#$perms & 8#077 )); then
    die "$env_file is mode $perms -- run: chmod 600 $env_file"
fi

set -a
# shellcheck source=/dev/null
source "$env_file"
set +a

[[ -x $poolstatus_bin ]] || die "$poolstatus_bin not found -- run: uv sync"

# The pool is in Sydney; this box may not be.  preferences.toml says which zone
# the report is written in, so the shell takes its clock from there too -- the
# send window below, the log stamps, the subject line.
TZ=$("$poolstatus_bin" prefs --timezone) || die "could not read preferences.toml"
export TZ

# SEND_AT="Sun 18" means: do nothing unless it is Sunday, 6pm, local to the
# pool.  For crons that only speak UTC -- run this hourly and set it.
: "${SEND_AT:=}"
if [[ -n $SEND_AT ]]; then
    read -r send_day send_hour _ <<< "$SEND_AT"
    [[ ${send_hour:-} =~ ^[0-9]{1,2}$ ]] \
        || die "SEND_AT should look like \"Sun 18\", got \"$SEND_AT\""
    if [[ $(date '+%a') != "$send_day" ]] || (( 10#$(date '+%H') != 10#$send_hour )); then
        exit 0
    fi
fi

for required in MAILGUN_API_KEY MAILGUN_DOMAIN MAIL_FROM MAIL_TO; do
    [[ -n ${!required:-} ]] || die "$required is not set in $env_file"
done

# api.eu.mailgun.net for EU-region domains.
: "${MAILGUN_API_BASE:=https://api.mailgun.net/v3}"
: "${MAIL_SUBJECT_PREFIX:=UNSW pool lanes}"
# Sent on a Sunday evening, the week worth reading about starts tomorrow.
: "${POOLSTATUS_ARGS:=--from tomorrow}"

read -ra report_args <<< "$POOLSTATUS_ARGS"

# --- build the report ------------------------------------------------------

workdir=$(mktemp -d)
trap 'rm -rf -- "$workdir"' EXIT

# One network hiccup should not cost the week's email.
render() {
    local attempt
    for attempt in 1 2 3; do
        if "$poolstatus_bin" "$@"; then
            return 0
        fi
        log "attempt $attempt of 'poolstatus $*' failed"
        sleep $(( attempt * 5 ))
    done
    return 1
}

render week --html "${report_args[@]}" > "$workdir/body.html" \
    || die "could not build the HTML report"
render week "${report_args[@]}" > "$workdir/body.txt" \
    || die "could not build the text report"

# Nice to have, not worth failing the email over.
"$poolstatus_bin" snapshot >/dev/null 2>&1 || log "warning: snapshot failed"

# Line 2 of the text report is the span it covers, e.g. "Mon 15 Sep to Sun 21
# Sep" -- a better subject than today's date, and it cannot drift from the body.
covered=$(sed -n '2p' "$workdir/body.txt")
subject="$MAIL_SUBJECT_PREFIX · ${covered:-$(date '+week of %-d %b')}"

# --- send ------------------------------------------------------------------

# The API key goes in a config file rather than on the command line, so it
# never shows up in ps output.
umask 077
printf 'user = "api:%s"\n' "$MAILGUN_API_KEY" > "$workdir/curlrc"

if response=$(curl --silent --show-error --fail-with-body \
        --config "$workdir/curlrc" \
        --url "$MAILGUN_API_BASE/$MAILGUN_DOMAIN/messages" \
        --form "from=$MAIL_FROM" \
        --form "to=$MAIL_TO" \
        --form "subject=$subject" \
        --form "text=<$workdir/body.txt" \
        --form "html=<$workdir/body.html" 2>&1); then
    log "sent to $MAIL_TO"
else
    die "mailgun rejected the message: $response"
fi
