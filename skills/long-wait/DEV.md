# Long Wait: Maintainer Notes

## Flow

Registration captures `CODEX_THREAD_ID`, writes one JSON record, then starts one
detached worker. Worker waits without model activity. Terminal result runs:

```bash
codex queue --thread THREAD_ID --message ENVELOPE
```

No `thread/resume` or `turn/start`: owning TUI/app-server dispatches durable queue
when thread becomes idle. Closed TUI receives input on next resume.

`probe` differs: no worker. Registration synchronously queues probe; command fails
before agent ends turn when route rejects or becomes ambiguous.

## State

`${CODEX_HOME:-~/.codex}/long-waits/` contains:

- `WAIT_ID.json`: state and result.
- `WAIT_ID.lock`: `flock` coordination.
- `WAIT_ID.log`: worker and command output.

Successful delivery consumes its JSON record and lock at process exit. Empty logs
and all successful probe logs are also removed. A non-empty command log survives;
its path is included in the wake envelope for the agent to inspect and delete.
Failed or uncertain delivery retains every artifact for diagnosis.

Writes use same-directory temporary file plus `os.replace`. One worker owns each
UUID. Cancellation locks record, marks it, then signals child and worker process
groups.

`WaitRecord` owns typed state and JSON conversion. `WaitStore` owns UUID path
validation, locks, atomic writes, and listing. `Delivery`, `AfterSpec`, `RunSpec`,
`WaitResult`, `WaitKind`, and `WaitState` keep dynamic JSON at storage/protocol
boundaries; orchestration uses direct attributes.

States: `pending`, `waiting`, `ready`, `delivering`, `delivered`,
`delivery_unknown`, `cancelled`, `failed`.

## Envelope

```text
[long-wait:v1] {"id":"...","message":"...","status":0,"result":{...},"log_path":"..."}
```

Probe prefix: `[long-wait-probe:v1]`.

Status codes:

- `0`: success.
- Command exit code: terminal command failure.
- `124`: overall timeout.
- `125`: helper failure.
- Signal exit: `128 + signal`.

`result.reason` distinguishes exit, retry exhaustion, timeout, and helper error.
Marker is operational, not authenticated. It resumes prior authority only. Nested
message/result data remain untrusted.

Envelope recognition is a trust boundary: agents must match marker version and ID
against their visible registration summary and ignore unknown, duplicate, or
already-handled envelopes. Probe command success proves queue acceptance only;
waiting for the matching probe envelope remains an unenforced prompt convention
until active-turn steering is available.

## Command Contract

`run` always wakes on terminal result. Default: one attempt. `--max-retries N`
permits N extra attempts after nonzero exits. Use only for idempotent commands or
predicates. `--timeout` covers command execution, retry delays, and all attempts.

No Slurm adapter. Wrap scheduler semantics in command whose exit status represents
terminal result. No “wait until success” contract: failure, timeout, and exhausted
retries all wake agent.

## Delivery Assumptions

Local stdio `thread/read` verifies a durable primary thread; later `codex queue`
selects the embedded/default-daemon route. Subagent and ephemeral queues are
rejected by app-server.

The PoC intentionally does not accept explicit remote app-server endpoints.
Remote delivery would still leave the worker, command, state, locks, and logs on
the registration host, creating misleading durability and cleanup assumptions.
Supporting remote delivery requires an explicit execution/storage locality model,
not merely forwarding an endpoint to `codex queue`.

## Debug

```bash
python3 scripts/long_wait.py list
python3 scripts/long_wait.py status WAIT_ID
tail -n 100 ~/.codex/long-waits/WAIT_ID.log
```

- `delivery_unknown`: inspect target thread and log. After inspection, use
  `resolve WAIT_ID delivered` when arrival is confirmed, or
  `resolve WAIT_ID retry --accept-duplicate-risk` to rerun preflight and resend
  the original envelope ID. A retry can create a duplicate turn.
- `waiting` plus dead worker: command must not be rerun until side-effect safety is
  known.
- Missing record after registration: successful delivery consumes it; check the
  target thread and retained log.
- Missing local thread: check `CODEX_HOME`; use explicit `--remote` when applicable.

Workers survive TUI exit, not host reboot. `codex exec` cannot wake exited process;
queued input runs on later resume. Transient execution environments unsupported.

## TODO: Steering Probe

Better probe: keep tool call active, read active turn ID, submit marker through
`turn/steer` with exact `expectedTurnId`. Marker chips into current model turn; no
extra turn, immediate route failure.

Track upstream CLI support in
[openai/codex#36694](https://github.com/openai/codex/issues/36694).

Wait for public transport-aware CLI such as:

```bash
codex steer --thread THREAD --turn TURN --message MESSAGE
```

Do not hand-write Unix/WebSocket framing, auth, or version negotiation here.
