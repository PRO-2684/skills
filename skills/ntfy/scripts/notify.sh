#!/usr/bin/env bash
set -euo pipefail

fail() { printf '%s\n' "$*" >&2; exit 2; }

if [[ -z ${NTFY_TOPIC:-} ]]; then
  fail 'NTFY_TOPIC is unset or empty. Generate it once: export NTFY_TOPIC="agent-$(uuidgen)". Save the literal value in your shell startup file, subscribe to that topic in ntfy, and relaunch the agent with it exported. See SKILL.md for setup commands.'
fi
[[ $NTFY_TOPIC =~ ^[A-Za-z0-9_-]+$ ]] || fail 'NTFY_TOPIC must contain only letters, digits, underscores, or hyphens; use a topic name, not a URL.'
(( $# >= 1 && $# <= 4 )) || fail 'Usage: notify.sh MESSAGE [TITLE [PRIORITY [TAGS]]]'
message=$1
title=${2-Agent notification}
priority=${3-default}
tags=${4-}
[[ -n $message ]] || fail 'Message must not be empty.'
for header in "$title" "$priority" "$tags"; do
  [[ $header != *$'\r'* && $header != *$'\n'* ]] || fail 'Title, priority, and tags must not contain newlines.'
done
case $priority in
  min|low|default|high|urgent|[1-5]) ;;
  *) fail 'Priority must be min, low, default, high, urgent, or 1-5.' ;;
esac
command -v curl >/dev/null || fail 'curl is required.'

# Send the body on stdin so leading @ is literal and multiline text is preserved.
status=$(printf '%s' "$message" | curl --disable \
  --silent --show-error --fail \
  --connect-timeout 10 --max-time 30 \
  --output /dev/null --write-out '%{http_code}' \
  --header 'Content-Type: text/plain; charset=utf-8' \
  --header "Title: $title" \
  --header "Priority: $priority" \
  --header "Tags: $tags" \
  --data-binary @- \
  "https://ntfy.sh/$NTFY_TOPIC") || {
    printf '%s\n' 'Notification request failed; delivery may be uncertain. No retry attempted.' >&2
    exit 1
  }
[[ $status == 2[0-9][0-9] ]] || {
  printf 'ntfy returned HTTP %s; notification not confirmed.\n' "$status" >&2
  exit 1
}
printf '%s\n' 'Notification accepted by ntfy.'
