#!/usr/bin/env bash
#
# Email today's lane availability via Mailgun.  Meant for cron:
#
#   30 6 * * * /home/james/projects/poolstatus/send_report.sh >> /home/james/projects/poolstatus/cron.log 2>&1
#
# Secrets live in poolstatus.env next to this script (gitignored) -- copy
# poolstatus.env.example and fill it in:
#
#   cp poolstatus.env.example poolstatus.env && chmod 600 poolstatus.env
#
# Also appends today's picture to data/history.jsonl, since the calendar API
# cannot be asked about the past -- the only way to accumulate history is to
# keep looking.

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
env_file="${POOLSTATUS_ENV:-$script_dir/poolstatus.env}"
poolstatus_bin="$script_dir/.venv/bin/poolstatus"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }
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

for required in MAILGUN_API_KEY MAILGUN_DOMAIN MAIL_FROM MAIL_TO; do
    [[ -n ${!required:-} ]] || die "$required is not set in $env_file"
done

# api.eu.mailgun.net for EU-region domains.
: "${MAILGUN_API_BASE:=https://api.mailgun.net/v3}"
: "${MAIL_SUBJECT_PREFIX:=UNSW pool lanes}"
: "${POOLSTATUS_ARGS:=}"

[[ -x $poolstatus_bin ]] || die "$poolstatus_bin not found -- run: uv sync"

read -ra report_args <<< "$POOLSTATUS_ARGS"

# --- build the report ------------------------------------------------------

workdir=$(mktemp -d)
trap 'rm -rf -- "$workdir"' EXIT

# One network hiccup at 6am should not cost the day's email.
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

render today --html "${report_args[@]}" > "$workdir/body.html" \
    || die "could not build the HTML report"
render today "${report_args[@]}" > "$workdir/body.txt" \
    || die "could not build the text report"

# Nice to have, not worth failing the email over.
"$poolstatus_bin" snapshot >/dev/null 2>&1 || log "warning: snapshot failed"

subject="$MAIL_SUBJECT_PREFIX · $(date '+%a %-d %b')"

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
