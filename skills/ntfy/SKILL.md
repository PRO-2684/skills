---
name: ntfy
description: Send the user push notifications through ntfy.sh using NTFY_TOPIC. Use when the user needs to be notified with a ntfy notification.
---

# ntfy

Send user-requested notifications using `scripts/notify.sh` by absolute path.
Requires Bash and curl.

## Setup

If `NTFY_TOPIC` is unset or empty, abort the notification and suggest generating
a topic and save it:

```bash
export NTFY_TOPIC="agent-$(uuidgen)"
printf 'export NTFY_TOPIC="%s"\n' "$NTFY_TOPIC" >> ~/.profile
```

Adapt `.profile` to the user's shell. Persist the generated value once, then
relaunch the agent with it exported. Have the user subscribe to that topic in
the ntfy [phone](https://docs.ntfy.sh/subscribe/phone/), [web app](https://docs.ntfy.sh/subscribe/web/) or other supported channels. Do not edit startup files automatically.

Anyone knowing an unprotected topic can read or publish. Keep it private and
omit sensitive message contents. The wrapper supports public ntfy.sh topics only.

## Send

Arguments: `MESSAGE [TITLE [PRIORITY [TAGS]]]`.

```bash
bash /absolute/path/to/ntfy/scripts/notify.sh \
  'The requested work is complete. Checks passed.' \
  'Task complete' default white_check_mark
```

Defaults: title `Agent notification`, priority `default`, no tags.
Priorities: `min`, `low`, `default`, `high`, `urgent`, or `1`–`5`.
Tags are comma-separated. Use normal priority unless urgency is warranted.

The wrapper makes one HTTPS attempt with a 30-second timeout. Report failures
separately from the task; do not automatically retry ambiguous delivery.
Success confirms server acceptance, not that the user received or read it.

API reference: [Publishing messages](https://docs.ntfy.sh/publish/).
