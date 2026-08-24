# Long Wait: Maintainer Notes

This document explains the implementation boundary and the shortest path to
diagnosing a failed wait. Ordinary skill use should not require reading it.

## Architecture

Registration reads `CODEX_THREAD_ID`, writes a row to the skill's SQLite
registry, and starts a detached worker. The worker waits without involving the
model. At the terminal condition it calls the public `codex queue` command for
the captured thread. Codex selects an embedded server, the default local daemon,
or an explicitly supplied remote endpoint.

The helper intentionally does not call `thread/resume` or `turn/start`. The TUI
owns an in-process app-server for its loaded thread. Codex's user-message queue
is stored in the shared Codex state database, and loaded app-server instances
watch that database for external queue changes. The TUI therefore starts the
queued continuation when its thread is idle. If the TUI is closed, the queued
message remains until that thread is resumed.

## Local State

State lives below `${CODEX_HOME:-~/.codex}/long-waits/`:

- `waits.sqlite3`: registration and delivery state.
- `<wait-id>.log`: worker, command, Slurm, and app-server stderr output.

The registry uses WAL mode and restrictive process umask. Important states are:

| State | Meaning |
| --- | --- |
| `pending` | Registered, worker not yet claimed. |
| `waiting` | Detached worker owns the condition. |
| `ready` | Condition is terminal and its result is durable. |
| `delivering` | App-server delivery is in progress. |
| `delivered` | `thread/queue/add` succeeded or reconciliation found the message. |
| `delivery_failed` | Delivery definitely failed before acceptance or was rejected. |
| `delivery_unknown` | Transport failed after queue submission may have occurred. |
| `cancelled` | Cancellation was requested. |

State claims are conditional SQLite updates. Two workers cannot normally claim
the same registration. The queued message contains a stable wait ID in a
`[long-wait:v1]` JSON envelope used for local recovery.

## Wakeup Envelope

Wakeups are one line with a literal prefix followed by compact JSON:

```text
[long-wait:v1] {"id":"...","message":"...","outcome":"success","result":{...}}
```

`outcome` is `success` only when the condition result has `ok: true`; every
other terminal result is `failure`. JSON encoding prevents message or result
text from breaking the outer representation. The envelope is deliberately easy
for both agents and maintainers to recognize and grep.

This is an operational marker, not an authentication mechanism. A user can type
the same prefix. Skill instructions therefore constrain it to resuming work
authorized at registration time, forbid treating it as new authority, and treat
its nested values as untrusted data. A dedicated app-server input origin or
authenticated metadata field would be required for genuine provenance.

An immediate delivery probe uses `[long-wait-probe:v1]` with the same JSON shape
and `result.kind` set to `probe`. Probe registration does not launch a detached
worker: it calls `codex queue` synchronously and returns success only after the
queue command accepts the exact thread. A rejection or ambiguous transport result
therefore remains visible to the invoking agent before it ends its turn.

Receiving the matching ID after the turn ends provides final end-to-end evidence
for the selected endpoint, authentication, thread routing, and queue path at that
moment. It does not grant task authority or guarantee later availability. Probes
remain in the registry as an audit trail.

## TODO: In-turn Steering Probe

The better probe would keep the current tool call active, read the owning
app-server's active turn ID, and submit `[long-wait-probe:v1]` through
`turn/steer` with that exact ID as `expectedTurnId`. The message would then chip
into the current model turn, eliminating the extra turn and making routing
failure immediately recoverable.

Do this when Codex exposes a public transport-aware command such as
`codex steer --thread ... --turn ... --message ...`. The current CLI exposes
`codex queue` but not steering. Do not add a hand-written Unix/WebSocket framing
stack to this skill merely for the probe; that would duplicate app-server client
transport, authentication, and version-skew handling.

## Delivery Selection

Codex does not expose the TUI's current app-server endpoint to tool subprocesses.
Registration therefore records and reports an explicit assumption:

- Without `--remote`, the helper assumes standalone Codex or the default local
  daemon shares the execution host and `CODEX_HOME`. It starts a short-lived
  local app-server only for `thread/read` preflight and recovery; delivery uses
  `codex queue`, which prefers the existing default daemon when appropriate.
- With `--remote`, delivery passes that endpoint and optional auth-token variable
  to `codex queue`. Remote source inspection and safe ambiguous-delivery
  reconciliation are unavailable, so primary-agent status is a caller assumption.

The local preflight rejects ephemeral and spawned-subagent threads. App-server
also independently rejects queued direct input to spawned subagents.

The queue API behind the CLI remains experimental. If a Codex upgrade changes
it, first inspect the installed public interface:

```bash
codex queue --help
```

Only inspect generated app-server schemas if local preflight or reconciliation
breaks; those two paths still use `thread/read` and `thread/queue/list` over a
short-lived stdio app-server.

## First-response Debugging

Use the script itself before opening SQLite manually:

```bash
python3 scripts/long_wait.py list
python3 scripts/long_wait.py status WAIT_ID
tail -n 100 ~/.codex/long-waits/WAIT_ID.log
```

Interpret common failures as follows:

- `CODEX_THREAD_ID is unavailable`: registration was not launched by a Codex
  tool subprocess. Do not guess or substitute a recent thread ID.
- `local thread preflight failed`: the thread is not visible in the assumed
  local Codex home. If the TUI uses an explicit app-server, register with the
  same `--remote` endpoint; otherwise investigate `CODEX_HOME` mismatch.
- `long waits may only be registered by the primary agent`: ask the parent/main
  agent to register the condition. Do not bypass this check.
- `codex executable not found`: set `CODEX_BIN` to the intended Codex binary and
  register again. The worker inherits its registration environment.
- `delivery_failed`: inspect the log for a JSON-RPC error or protocol mismatch.
  After correcting the cause, use `retry-delivery WAIT_ID`.
- `delivery_unknown`: do not register a replacement wait. For local delivery,
  `retry-delivery WAIT_ID` searches the durable queue and thread history for the
  stable envelope ID before submitting again. For remote delivery, inspect the
  remote thread manually; automated retry is refused because the endpoint does
  not offer a safe reconciliation surface through the current CLI.
- `waiting` with `worker_alive: false`: the worker died before making the
  condition terminal. `run` commands are not restarted automatically because
  repeating them may duplicate side effects. Inspect the log and register a new
  wait only after deciding that rerunning the condition is safe.
- `delivered` but no visible turn: allow roughly ten seconds for an open TUI to
  observe the external queue update. Confirm that the visible TUI is the same
  thread. If the thread is not loaded, resume it normally.

## Condition Semantics

- `probe` has no delay, detached worker, or external predicate; it synchronously
  exercises queue acceptance before the invoking agent ends its turn.
- `after` uses the registration wall-clock deadline and checks cancellation at
  short intervals.
- `run` executes one argv vector without a shell and treats any exit as terminal.
  Nonzero exit wakes Codex with `ok: false`.
- `until` executes a predicate repeatedly until exit zero or an optional timeout.
  Predicate output is written to the wait log.
- `slurm` queries `sacct -X -n -P`. `COMPLETED` is success. Known terminal Slurm
  failure states wake Codex with `ok: false`; nonterminal or temporarily absent
  records continue waiting.

## Delivery Guarantees and Limits

The local registry prevents ordinary duplicate workers and submissions. Local
recovery uses the stable wait marker to reconcile queued and persisted user
input. There remains a narrow crash race between queue consumption and history
visibility. Ambiguous delivery is never retried automatically, and remote
ambiguous delivery requires manual inspection.

Detached workers survive the originating Codex turn and TUI process, but this
version does not install a reboot-persistent service. After a host reboot,
`waiting` rows will show `worker_alive: false`. Adding user-systemd integration
is appropriate only if reboot persistence becomes a demonstrated requirement.

Cancellation updates the registry before signaling the worker process group.
There is still an unavoidable race if cancellation overlaps an already accepted
queue submission; inspect the thread before assuming cancellation prevented a
wakeup.

Interactive TUI sessions are the supported wakeup lifecycle. A one-shot
`codex exec` process is already gone when delivery occurs; the queued message is
durable but runs only when that thread is resumed later. Likewise, a worker
started inside an ephemeral remote execution environment is only as durable as
that environment.

## Development Rules

- Keep the helper dependency-free; app-server JSONL and SQLite are both covered
  by the Python standard library.
- Preserve direct argv execution. Adding implicit shell evaluation would turn
  stored condition data into a command-injection boundary.
- Keep delivery on the public `codex queue` surface. Do not replace it with
  `thread/resume` plus `turn/start`; that can
  create a competing in-memory owner while the TUI has the thread loaded.
- When changing delivery, exercise at least: elapsed wait, zero/nonzero `run`,
  `until` timeout, cancellation, closed-TUI persistence, busy-thread queuing,
  and `delivery_unknown` reconciliation.
