#!/usr/bin/env python3
"""Register detached waits and wake the originating Codex thread."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any


TERMINAL_STATES = {"delivered", "cancelled"}
DELIVERY_RETRY_STATES = {"delivery_failed", "delivery_unknown"}
SLURM_FAILURE_STATES = {
    "BOOT_FAIL",
    "CANCELLED",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "REVOKED",
    "SPECIAL_EXIT",
    "TIMEOUT",
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS waits (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    message TEXT NOT NULL,
    client_message_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    pid INTEGER,
    created_at REAL NOT NULL,
    started_at REAL,
    condition_at REAL,
    delivered_at REAL,
    result_json TEXT,
    error TEXT,
    log_path TEXT NOT NULL
)
"""


class RpcError(RuntimeError):
    pass


def state_dir() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    base = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    value = base / "long-waits"
    value.mkdir(mode=0o700, parents=True, exist_ok=True)
    return value


def database_path() -> Path:
    return state_dir() / "waits.sqlite3"


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(database_path(), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute(SCHEMA)
    connection.commit()
    return connection


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    for field in ("spec_json", "result_json"):
        if value.get(field):
            value[field.removesuffix("_json")] = json.loads(value.pop(field))
        else:
            value.pop(field, None)
    value["worker_alive"] = pid_alive(value.get("pid"))
    return value


def emit(value: Any) -> None:
    json.dump(value, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def parse_duration(raw: str) -> float:
    match = re.fullmatch(r"(\d+)([smhd])", raw.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError("duration must look like 30s, 10m, 6h, or 2d")
    amount = int(match.group(1))
    scale = {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    return float(amount * scale)


def command_value(values: list[str]) -> list[str]:
    command = values[1:] if values[:1] == ["--"] else values
    if not command:
        raise ValueError("a command is required after --")
    return command


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def is_cancelled(wait_id: str) -> bool:
    with connect() as connection:
        row = connection.execute("SELECT state FROM waits WHERE id = ?", (wait_id,)).fetchone()
    return row is None or row["state"] == "cancelled"


def update_wait(wait_id: str, fields: dict[str, Any], expected: set[str] | None = None) -> bool:
    assignments = ", ".join(f"{name} = ?" for name in fields)
    values = list(fields.values())
    where = "id = ?"
    values.append(wait_id)
    if expected:
        placeholders = ", ".join("?" for _ in expected)
        where += f" AND state IN ({placeholders})"
        values.extend(sorted(expected))
    with connect() as connection:
        cursor = connection.execute(f"UPDATE waits SET {assignments} WHERE {where}", values)
        connection.commit()
    return cursor.rowcount == 1


def spawn_worker(wait_id: str, log_path: Path) -> int:
    script = Path(__file__).resolve()
    with log_path.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            [sys.executable, str(script), "_worker", wait_id],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=state_dir(),
            start_new_session=True,
            close_fds=True,
        )
    return process.pid


def delivery_value(remote: str | None, remote_auth_token_env: str | None) -> dict[str, Any]:
    if remote_auth_token_env and not remote:
        raise ValueError("--remote-auth-token-env requires --remote")
    if remote:
        return {
            "mode": "explicit_remote",
            "endpoint": remote,
            "auth_token_env": remote_auth_token_env,
            "assumption": (
                "Assuming the supplied endpoint is the app-server that owns this thread and "
                "that registration is running in the primary agent; remote thread source cannot be preflighted."
            ),
        }
    return {
        "mode": "local_auto",
        "assumption": (
            "Assuming standalone Codex or the default local daemon shares this execution host and CODEX_HOME."
        ),
    }


def preflight_registration(thread_id: str, delivery: dict[str, Any]) -> str:
    if delivery["mode"] == "explicit_remote":
        return delivery["assumption"]
    client: AppServerClient | None = None
    try:
        client = AppServerClient()
        result = client.call("thread/read", {"threadId": thread_id, "includeTurns": False})
        thread = result["thread"]
        source = thread.get("source")
        if thread.get("ephemeral"):
            raise RuntimeError("the current thread is ephemeral and cannot receive durable queued input")
        if (
            thread.get("parentThreadId")
            or thread.get("threadSource") == "subagent"
            or isinstance(source, dict) and "subAgent" in source
        ):
            raise RuntimeError("long waits may only be registered by the primary agent")
    except RpcError as error:
        raise RuntimeError(
            f"local thread preflight failed ({error}); if this Codex uses an explicit app-server, pass --remote"
        ) from error
    finally:
        if client is not None:
            client.close()
    return delivery["assumption"] + " Durable primary thread verified through local thread/read."


def register(
    kind: str,
    spec: dict[str, Any],
    message: str,
    delivery: dict[str, Any],
) -> dict[str, Any]:
    thread_id = os.environ.get("CODEX_THREAD_ID")
    if not thread_id:
        raise RuntimeError("CODEX_THREAD_ID is unavailable; run registration from a Codex tool command")
    assumption = preflight_registration(thread_id, delivery)
    spec["delivery"] = delivery
    wait_id = str(uuid.uuid4())
    log_path = state_dir() / f"{wait_id}.log"
    client_message_id = f"codex-long-wait:{wait_id}"
    created_at = time.time()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO waits (
                id, thread_id, kind, spec_json, message, client_message_id,
                state, created_at, log_path
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                wait_id,
                thread_id,
                kind,
                json.dumps(spec),
                message,
                client_message_id,
                created_at,
                str(log_path),
            ),
        )
        connection.commit()
    pid: int | None = None
    state = "pending"
    try:
        if kind == "probe":
            result = wait_probe()
            update_wait(
                wait_id,
                {
                    "state": "ready",
                    "condition_at": time.time(),
                    "result_json": json.dumps(result),
                },
                {"pending"},
            )
            deliver(wait_id, reconcile=False)
            probe_row = get_wait(wait_id)
            state = probe_row["state"]
            if state != "delivered":
                raise RuntimeError(
                    f"probe {wait_id} was not accepted: {state}: {probe_row['error']}"
                )
        else:
            pid = spawn_worker(wait_id, log_path)
            update_wait(wait_id, {"pid": pid})
    except Exception as error:
        if kind != "probe":
            update_wait(
                wait_id,
                {"state": "delivery_failed", "error": f"worker launch failed: {error}"},
            )
        raise
    return {
        "id": wait_id,
        "thread_id": thread_id,
        "state": state,
        "pid": pid,
        "log_path": str(log_path),
        "delivery_assumption": assumption,
    }


def wait_after(wait_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    deadline = spec["registered_at"] + spec["seconds"]
    while time.time() < deadline:
        if is_cancelled(wait_id):
            raise InterruptedError("wait cancelled")
        time.sleep(min(5, max(0, deadline - time.time())))
    return {"ok": True, "kind": "after", "elapsed_seconds": spec["seconds"]}


def wait_probe() -> dict[str, Any]:
    return {"ok": True, "kind": "probe"}


def wait_run(wait_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    process = subprocess.Popen(spec["command"])
    while process.poll() is None:
        if is_cancelled(wait_id):
            process.terminate()
            raise InterruptedError("wait cancelled")
        time.sleep(1)
    return {
        "ok": process.returncode == 0,
        "kind": "run",
        "command": spec["command"],
        "exit_code": process.returncode,
        "elapsed_seconds": round(time.time() - started, 3),
    }


def wait_until(wait_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    attempts = 0
    while True:
        if is_cancelled(wait_id):
            raise InterruptedError("wait cancelled")
        attempts += 1
        result = subprocess.run(spec["command"], check=False)
        if result.returncode == 0:
            return {"ok": True, "kind": "until", "attempts": attempts, "command": spec["command"]}
        timeout = spec.get("timeout")
        if timeout is not None and time.time() - started >= timeout:
            return {
                "ok": False,
                "kind": "until",
                "attempts": attempts,
                "command": spec["command"],
                "error": "predicate timeout",
                "last_exit_code": result.returncode,
            }
        time.sleep(spec["interval"])


def slurm_states(job_id: str) -> list[str]:
    result = subprocess.run(
        ["sacct", "-X", "-n", "-P", "-j", job_id, "-o", "State"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"sacct exited {result.returncode}: {result.stderr.strip()}")
    return [line.split("|", 1)[0].strip().split("+", 1)[0] for line in result.stdout.splitlines() if line.strip()]


def wait_slurm(wait_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    while True:
        if is_cancelled(wait_id):
            raise InterruptedError("wait cancelled")
        states = slurm_states(spec["job_id"])
        failures = sorted(set(states) & SLURM_FAILURE_STATES)
        if failures:
            return {"ok": False, "kind": "slurm", "job_id": spec["job_id"], "states": states}
        if states and all(state == "COMPLETED" for state in states):
            return {"ok": True, "kind": "slurm", "job_id": spec["job_id"], "states": states}
        timeout = spec.get("timeout")
        if timeout is not None and time.time() - started >= timeout:
            return {"ok": False, "kind": "slurm", "job_id": spec["job_id"], "states": states, "error": "Slurm wait timeout"}
        time.sleep(spec["interval"])


def wait_for_condition(wait_id: str, kind: str, spec: dict[str, Any]) -> dict[str, Any]:
    if kind == "probe":
        return wait_probe()
    if kind == "after":
        return wait_after(wait_id, spec)
    if kind == "run":
        return wait_run(wait_id, spec)
    if kind == "until":
        return wait_until(wait_id, spec)
    if kind == "slurm":
        return wait_slurm(wait_id, spec)
    raise RuntimeError(f"unknown wait kind: {kind}")


class AppServerClient:
    def __init__(self) -> None:
        codex = os.environ.get("CODEX_BIN") or shutil.which("codex")
        if not codex:
            raise RuntimeError("codex executable not found; set CODEX_BIN for the detached worker")
        self.process = subprocess.Popen(
            [codex, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1,
        )
        self.next_id = 1
        self.call(
            "initialize",
            {
                "clientInfo": {"name": "long_wait", "title": "Long Wait", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        self.send({"method": "initialized"})

    def send(self, message: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise RuntimeError("app-server stdin is unavailable")
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def call(self, method: str, params: dict[str, Any]) -> Any:
        request_id = self.next_id
        self.next_id += 1
        self.send({"id": request_id, "method": method, "params": params})
        if self.process.stdout is None:
            raise RuntimeError("app-server stdout is unavailable")
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError(f"app-server closed while waiting for {method}")
            message = json.loads(line)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                raise RpcError(f"{method}: {error.get('code')}: {error.get('message')}")
            return message.get("result")

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=2)


def contains_marker(value: Any, marker: str) -> bool:
    if isinstance(value, dict):
        return any(contains_marker(item, marker) for item in value.values())
    if isinstance(value, list):
        return any(contains_marker(item, marker) for item in value)
    return isinstance(value, str) and marker in value


def already_delivered(client: AppServerClient, thread_id: str, marker: str) -> bool:
    cursor: str | None = None
    while True:
        result = client.call(
            "thread/queue/list",
            {"threadId": thread_id, "cursor": cursor, "limit": 100},
        )
        if contains_marker(result.get("data", []), marker):
            return True
        cursor = result.get("nextCursor")
        if not cursor:
            break
    history = client.call("thread/read", {"threadId": thread_id, "includeTurns": True})
    return contains_marker(history, marker)


def continuation_text(row: sqlite3.Row) -> str:
    result = json.loads(row["result_json"])
    payload = {
        "id": row["id"],
        "message": row["message"],
        "outcome": "success" if result.get("ok") is True else "failure",
        "result": result,
    }
    marker = "[long-wait-probe:v1]" if row["kind"] == "probe" else "[long-wait:v1]"
    return marker + " " + json.dumps(payload, separators=(",", ":"), sort_keys=True)


def queue_command(row: sqlite3.Row, delivery: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    codex = os.environ.get("CODEX_BIN") or shutil.which("codex")
    if not codex:
        raise RuntimeError("codex executable not found; set CODEX_BIN for the detached worker")
    command = [
        codex,
        "queue",
        "--thread",
        row["thread_id"],
        "--message",
        continuation_text(row),
    ]
    if delivery["mode"] == "explicit_remote":
        command.extend(["--remote", delivery["endpoint"]])
        if auth_env := delivery.get("auth_token_env"):
            command.extend(["--remote-auth-token-env", auth_env])
    return subprocess.run(command, check=False, capture_output=True, text=True)


def deliver(wait_id: str, reconcile: bool) -> None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM waits WHERE id = ?", (wait_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"unknown wait ID: {wait_id}")
    delivery = json.loads(row["spec_json"])["delivery"]
    if reconcile and delivery["mode"] == "explicit_remote":
        raise RuntimeError(
            "remote delivery cannot be reconciled safely; inspect the remote thread before registering a replacement"
        )
    expected = DELIVERY_RETRY_STATES | {"ready"}
    if not update_wait(wait_id, {"state": "delivering", "error": None}, expected):
        raise RuntimeError("wait is not ready for delivery")
    client: AppServerClient | None = None
    add_attempted = False
    try:
        if reconcile:
            client = AppServerClient()
            if already_delivered(client, row["thread_id"], f'"id":"{wait_id}"'):
                update_wait(wait_id, {"state": "delivered", "delivered_at": time.time()}, {"delivering"})
                return
        add_attempted = True
        result = queue_command(row, delivery)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"codex queue exited {result.returncode}"
            update_wait(wait_id, {"state": "delivery_unknown", "error": detail}, {"delivering"})
            return
        update_wait(wait_id, {"state": "delivered", "delivered_at": time.time()}, {"delivering"})
    except Exception as error:
        state = "delivery_unknown" if add_attempted else "delivery_failed"
        update_wait(wait_id, {"state": state, "error": str(error)}, {"delivering"})
    finally:
        if client is not None:
            client.close()


def worker(wait_id: str) -> int:
    claimed = update_wait(
        wait_id,
        {"state": "waiting", "started_at": time.time(), "pid": os.getpid(), "error": None},
        {"pending"},
    )
    if not claimed:
        return 0
    with connect() as connection:
        row = connection.execute("SELECT * FROM waits WHERE id = ?", (wait_id,)).fetchone()
    if row is None:
        return 1
    try:
        result = wait_for_condition(wait_id, row["kind"], json.loads(row["spec_json"]))
    except InterruptedError:
        return 0
    except Exception as error:
        result = {"ok": False, "kind": row["kind"], "error": str(error)}
    if not update_wait(
        wait_id,
        {"state": "ready", "condition_at": time.time(), "result_json": json.dumps(result)},
        {"waiting"},
    ):
        return 0
    deliver(wait_id, reconcile=False)
    return 0


def get_wait(wait_id: str) -> sqlite3.Row:
    with connect() as connection:
        row = connection.execute("SELECT * FROM waits WHERE id = ?", (wait_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown wait ID: {wait_id}")
    return row


def cancel(wait_id: str) -> dict[str, Any]:
    row = get_wait(wait_id)
    if row["state"] in TERMINAL_STATES:
        return row_dict(row)
    update_wait(wait_id, {"state": "cancelled", "error": "cancelled by user"})
    pid = row["pid"]
    if pid_alive(pid):
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    return row_dict(get_wait(wait_id))


def retry_delivery(wait_id: str) -> dict[str, Any]:
    row = get_wait(wait_id)
    if row["state"] == "delivering" and pid_alive(row["pid"]):
        raise RuntimeError("the original delivery worker is still running")
    if row["state"] == "delivering":
        update_wait(wait_id, {"state": "delivery_unknown"}, {"delivering"})
    elif row["state"] not in DELIVERY_RETRY_STATES:
        raise RuntimeError(f"delivery cannot be retried from state {row['state']}")
    deliver(wait_id, reconcile=True)
    return row_dict(get_wait(wait_id))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Wait independently, then continue the current Codex thread.")
    subparsers = parser.add_subparsers(dest="action", required=True)
    default_message = "The registered long wait has finished. Continue the prior task using the completion details below."

    def add_delivery_arguments(value: argparse.ArgumentParser) -> None:
        value.add_argument(
            "--remote",
            help="owning app-server endpoint: ws://, wss://, unix://, or unix://PATH",
        )
        value.add_argument(
            "--remote-auth-token-env",
            help="environment variable containing the remote WebSocket bearer token",
        )

    probe = subparsers.add_parser("probe", help="verify end-to-end delivery to this thread")
    probe.add_argument(
        "--message",
        default="Long-wait delivery probe succeeded. Confirm the matching ID and perform no additional work.",
    )
    add_delivery_arguments(probe)

    after = subparsers.add_parser("after", help="wake after an elapsed duration")
    after.add_argument("duration", type=parse_duration)
    after.add_argument("--message", default=default_message)
    add_delivery_arguments(after)

    run = subparsers.add_parser("run", help="run a command and wake when it exits")
    run.add_argument("--message", default=default_message)
    add_delivery_arguments(run)
    run.add_argument("command", nargs=argparse.REMAINDER)

    until = subparsers.add_parser("until", help="wake when a predicate command exits zero")
    until.add_argument("--interval", type=float, default=30)
    until.add_argument("--timeout", type=parse_duration)
    until.add_argument("--message", default=default_message)
    add_delivery_arguments(until)
    until.add_argument("command", nargs=argparse.REMAINDER)

    slurm = subparsers.add_parser("slurm", help="wake when a Slurm job reaches a terminal state")
    slurm.add_argument("job_id")
    slurm.add_argument("--interval", type=float, default=30)
    slurm.add_argument("--timeout", type=parse_duration)
    slurm.add_argument("--message", default=default_message)
    add_delivery_arguments(slurm)

    subparsers.add_parser("list", help="list registered waits")
    status = subparsers.add_parser("status", help="show one registered wait")
    status.add_argument("wait_id")
    cancel_parser = subparsers.add_parser("cancel", help="cancel a registered wait")
    cancel_parser.add_argument("wait_id")
    retry = subparsers.add_parser("retry-delivery", help="reconcile and retry an ambiguous delivery")
    retry.add_argument("wait_id")
    worker_parser = subparsers.add_parser("_worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("wait_id")
    return parser


def main() -> int:
    os.umask(0o077)
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.action == "probe":
            emit(register("probe", {}, args.message, delivery_value(args.remote, args.remote_auth_token_env)))
        elif args.action == "after":
            emit(register("after", {"seconds": args.duration, "registered_at": time.time()}, args.message, delivery_value(args.remote, args.remote_auth_token_env)))
        elif args.action == "run":
            emit(register("run", {"command": command_value(args.command)}, args.message, delivery_value(args.remote, args.remote_auth_token_env)))
        elif args.action == "until":
            emit(register("until", {"command": command_value(args.command), "interval": args.interval, "timeout": args.timeout}, args.message, delivery_value(args.remote, args.remote_auth_token_env)))
        elif args.action == "slurm":
            emit(register("slurm", {"job_id": args.job_id, "interval": args.interval, "timeout": args.timeout}, args.message, delivery_value(args.remote, args.remote_auth_token_env)))
        elif args.action == "list":
            with connect() as connection:
                rows = connection.execute("SELECT * FROM waits ORDER BY created_at DESC").fetchall()
            emit([row_dict(row) for row in rows])
        elif args.action == "status":
            emit(row_dict(get_wait(args.wait_id)))
        elif args.action == "cancel":
            emit(cancel(args.wait_id))
        elif args.action == "retry-delivery":
            emit(retry_delivery(args.wait_id))
        elif args.action == "_worker":
            return worker(args.wait_id)
        return 0
    except Exception as error:
        print(f"{parser.prog}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
