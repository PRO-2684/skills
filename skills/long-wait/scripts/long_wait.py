#!/usr/bin/env python3
"""Wait outside agent turns, then queue input to originating Codex thread."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, cast


JsonObject = dict[str, object]
TERMINAL_STATES = {"delivered", "cancelled"}


class RpcError(RuntimeError):
    pass


def state_dir() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    root = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    path = root / "long-waits"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def checked_id(wait_id: str) -> str:
    return str(uuid.UUID(wait_id))


def record_path(wait_id: str) -> Path:
    return state_dir() / f"{checked_id(wait_id)}.json"


@contextmanager
def record_lock(wait_id: str) -> Iterator[None]:
    path = state_dir() / f"{checked_id(wait_id)}.lock"
    with path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def load_unlocked(wait_id: str) -> JsonObject:
    path = record_path(wait_id)
    if not path.exists():
        raise ValueError(f"unknown wait ID: {wait_id}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"invalid wait record: {wait_id}")
    return cast(JsonObject, value)


def load_record(wait_id: str) -> JsonObject:
    with record_lock(wait_id):
        return load_unlocked(wait_id)


def save_unlocked(record: JsonObject) -> None:
    path = record_path(str(record["id"]))
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def create_record(record: JsonObject) -> None:
    wait_id = str(record["id"])
    with record_lock(wait_id):
        if record_path(wait_id).exists():
            raise RuntimeError(f"wait already exists: {wait_id}")
        save_unlocked(record)


def update_record(
    wait_id: str,
    fields: JsonObject,
    expected: set[str] | None = None,
) -> JsonObject | None:
    with record_lock(wait_id):
        record = load_unlocked(wait_id)
        if expected and record.get("state") not in expected:
            return None
        record.update(fields)
        save_unlocked(record)
        return record


def pid_alive(value: object) -> bool:
    if not isinstance(value, int) or value <= 0:
        return False
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def public_record(record: JsonObject) -> JsonObject:
    value = dict(record)
    value["worker_alive"] = pid_alive(record.get("pid"))
    return value


def emit(value: object) -> None:
    json.dump(value, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def parse_duration(raw: str) -> float:
    match = re.fullmatch(r"(\d+)([smhd])", raw.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError("duration must look like 30s, 10m, 6h, or 2d")
    scale = {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    return float(int(match.group(1)) * scale)


def nonnegative(raw: str) -> int:
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError("value must be nonnegative")
    return value


def command_value(values: list[str]) -> list[str]:
    command = values[1:] if values[:1] == ["--"] else values
    if not command:
        raise ValueError("command required after --")
    return command


class AppServerClient:
    """Minimal local stdio client used only for registration preflight."""

    def __init__(self) -> None:
        codex = os.environ.get("CODEX_BIN") or shutil.which("codex")
        if not codex:
            raise RuntimeError("codex executable not found; set CODEX_BIN")
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
                "clientInfo": {"name": "long_wait", "title": "Long Wait", "version": "0.2.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        self.send({"method": "initialized"})

    def send(self, message: JsonObject) -> None:
        if self.process.stdin is None:
            raise RuntimeError("app-server stdin unavailable")
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def call(self, method: str, params: JsonObject) -> JsonObject:
        request_id = self.next_id
        self.next_id += 1
        self.send({"id": request_id, "method": method, "params": params})
        if self.process.stdout is None:
            raise RuntimeError("app-server stdout unavailable")
        while line := self.process.stdout.readline():
            value = json.loads(line)
            if not isinstance(value, dict) or value.get("id") != request_id:
                continue
            if "error" in value:
                raise RpcError(f"{method}: {value['error']}")
            result = value.get("result")
            if not isinstance(result, dict):
                raise RpcError(f"{method}: invalid response")
            return cast(JsonObject, result)
        raise RuntimeError(f"app-server closed during {method}")

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=2)


def delivery_value(remote: str | None, auth_env: str | None) -> JsonObject:
    if auth_env and not remote:
        raise ValueError("--remote-auth-token-env requires --remote")
    if remote:
        return {
            "mode": "explicit_remote",
            "endpoint": remote,
            "auth_token_env": auth_env,
            "assumption": "Supplied endpoint owns thread; caller is primary agent.",
        }
    return {
        "mode": "local_auto",
        "assumption": "Standalone Codex or default local daemon shares host and CODEX_HOME.",
    }


def preflight(thread_id: str, delivery: JsonObject) -> str:
    if delivery["mode"] == "explicit_remote":
        return str(delivery["assumption"])
    client: AppServerClient | None = None
    try:
        client = AppServerClient()
        response = client.call("thread/read", {"threadId": thread_id, "includeTurns": False})
        thread = response.get("thread")
        if not isinstance(thread, dict):
            raise RuntimeError("thread/read omitted thread")
        source = thread.get("source")
        if thread.get("ephemeral"):
            raise RuntimeError("ephemeral thread cannot receive durable input")
        if (
            thread.get("parentThreadId")
            or thread.get("threadSource") == "subagent"
            or isinstance(source, dict) and "subAgent" in source
        ):
            raise RuntimeError("primary agent required")
    except RpcError as error:
        raise RuntimeError(f"local preflight failed ({error}); pass --remote when needed") from error
    finally:
        if client:
            client.close()
    return str(delivery["assumption"]) + " Durable primary thread verified."


def queue_message(record: JsonObject) -> subprocess.CompletedProcess[str]:
    codex = os.environ.get("CODEX_BIN") or shutil.which("codex")
    if not codex:
        raise RuntimeError("codex executable not found; set CODEX_BIN")
    result = cast(JsonObject, record["result"])
    payload: JsonObject = {
        "id": record["id"],
        "message": record["message"],
        "status": result["status"],
        "result": result,
    }
    marker = "[long-wait-probe:v1]" if record["kind"] == "probe" else "[long-wait:v1]"
    message = marker + " " + json.dumps(payload, separators=(",", ":"), sort_keys=True)
    command = [codex, "queue", "--thread", str(record["thread_id"]), "--message", message]
    delivery = cast(JsonObject, record["delivery"])
    if delivery["mode"] == "explicit_remote":
        command.extend(["--remote", str(delivery["endpoint"])])
        if auth_env := delivery.get("auth_token_env"):
            command.extend(["--remote-auth-token-env", str(auth_env)])
    return subprocess.run(command, check=False, capture_output=True, text=True)


def deliver(wait_id: str) -> None:
    if update_record(wait_id, {"state": "delivering", "error": None}, {"ready"}) is None:
        raise RuntimeError("wait not ready for delivery")
    try:
        result = queue_message(load_record(wait_id))
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip() or f"codex queue exited {result.returncode}"
            update_record(wait_id, {"state": "delivery_unknown", "error": detail}, {"delivering"})
            return
        update_record(wait_id, {"state": "delivered", "delivered_at": time.time()}, {"delivering"})
    except Exception as error:
        update_record(wait_id, {"state": "delivery_unknown", "error": str(error)}, {"delivering"})


def spawn_worker(wait_id: str, log_path: Path) -> int:
    with log_path.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_worker", wait_id],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=state_dir(),
            start_new_session=True,
            close_fds=True,
        )
    return process.pid


def register(kind: str, spec: JsonObject, message: str, delivery: JsonObject) -> JsonObject:
    thread_id = os.environ.get("CODEX_THREAD_ID")
    if not thread_id:
        raise RuntimeError("CODEX_THREAD_ID unavailable; register from Codex tool command")
    assumption = preflight(thread_id, delivery)
    wait_id = str(uuid.uuid4())
    log_path = state_dir() / f"{wait_id}.log"
    record: JsonObject = {
        "id": wait_id,
        "thread_id": thread_id,
        "kind": kind,
        "spec": spec,
        "message": message,
        "delivery": delivery,
        "delivery_assumption": assumption,
        "state": "pending",
        "pid": None,
        "child_pid": None,
        "created_at": time.time(),
        "log_path": str(log_path),
        "result": None,
        "error": None,
    }
    create_record(record)
    if kind == "probe":
        update_record(wait_id, {"state": "ready", "result": {"kind": "probe", "status": 0}})
        deliver(wait_id)
        record = load_record(wait_id)
        if record["state"] != "delivered":
            raise RuntimeError(f"probe {wait_id} not accepted: {record['state']}: {record['error']}")
    else:
        try:
            pid = spawn_worker(wait_id, log_path)
            update_record(wait_id, {"pid": pid})
        except Exception as error:
            update_record(wait_id, {"state": "failed", "error": str(error)})
            raise
    return public_record(load_record(wait_id))


def cancelled(wait_id: str) -> bool:
    return load_record(wait_id)["state"] == "cancelled"


def sleep_until(wait_id: str, deadline: float) -> bool:
    while time.time() < deadline:
        if cancelled(wait_id):
            return False
        time.sleep(min(1, max(0, deadline - time.time())))
    return True


def after_result(wait_id: str, spec: JsonObject) -> JsonObject | None:
    seconds = float(cast(float, spec["seconds"]))
    deadline = float(cast(float, spec["registered_at"])) + seconds
    if not sleep_until(wait_id, deadline):
        return None
    return {"kind": "after", "status": 0, "elapsed_seconds": seconds}


def stop_process(process: subprocess.Popen[object]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def timeout_result(started: float, attempt: int) -> JsonObject:
    return {
        "kind": "run",
        "status": 124,
        "reason": "timeout",
        "attempts": attempt,
        "elapsed_seconds": round(time.time() - started, 3),
    }


def run_result(wait_id: str, spec: JsonObject) -> JsonObject | None:
    command = cast(list[str], spec["command"])
    timeout = cast(float | None, spec["timeout"])
    max_retries = int(cast(int, spec["max_retries"]))
    retry_delay = float(cast(float, spec["retry_delay"]))
    started = time.time()
    deadline = started + timeout if timeout is not None else None
    for attempt in range(1, max_retries + 2):
        if cancelled(wait_id):
            return None
        if deadline is not None and time.time() >= deadline:
            return timeout_result(started, attempt)
        process = subprocess.Popen(command, start_new_session=True)
        update_record(wait_id, {"child_pid": process.pid})
        while process.poll() is None:
            if cancelled(wait_id):
                stop_process(process)
                return None
            if deadline is not None and time.time() >= deadline:
                stop_process(process)
                update_record(wait_id, {"child_pid": None})
                return timeout_result(started, attempt)
            time.sleep(0.5)
        update_record(wait_id, {"child_pid": None})
        code = process.returncode
        status = code if code >= 0 else 128 - code
        if status == 0 or attempt > max_retries:
            return {
                "kind": "run",
                "status": status,
                "reason": "exited" if status == 0 else "retries_exhausted",
                "attempts": attempt,
                "elapsed_seconds": round(time.time() - started, 3),
            }
        retry_deadline = time.time() + retry_delay
        if deadline is not None:
            retry_deadline = min(retry_deadline, deadline)
        if not sleep_until(wait_id, retry_deadline):
            return None
    raise AssertionError("unreachable")


def worker(wait_id: str) -> int:
    if update_record(wait_id, {"state": "waiting", "pid": os.getpid()}, {"pending"}) is None:
        return 0
    record = load_record(wait_id)
    try:
        spec = cast(JsonObject, record["spec"])
        result = after_result(wait_id, spec) if record["kind"] == "after" else run_result(wait_id, spec)
    except Exception as error:
        result = {"kind": record["kind"], "status": 125, "reason": "helper_error", "error": str(error)}
    if result is None:
        return 0
    if update_record(wait_id, {"state": "ready", "result": result, "condition_at": time.time()}, {"waiting"}) is not None:
        deliver(wait_id)
    return 0


def kill_group(value: object) -> None:
    if not isinstance(value, int) or value <= 0:
        return
    try:
        os.killpg(value, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def cancel(wait_id: str) -> JsonObject:
    record = load_record(wait_id)
    if record["state"] in TERMINAL_STATES:
        return public_record(record)
    updated = update_record(wait_id, {"state": "cancelled", "error": "cancelled"})
    assert updated is not None
    kill_group(record.get("child_pid"))
    kill_group(record.get("pid"))
    return public_record(load_record(wait_id))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Wait independently, then continue current Codex thread.")
    actions = parser.add_subparsers(dest="action", required=True)
    default_message = "Long wait reached a terminal result. Continue prior task using attached result."

    def delivery_args(value: argparse.ArgumentParser) -> None:
        value.add_argument("--remote", help="owning app-server ws://, wss://, or unix:// endpoint")
        value.add_argument("--remote-auth-token-env", help="environment variable containing bearer token")
        value.add_argument("--message", default=default_message, help="continuation note in wake envelope")

    probe = actions.add_parser("probe", help="synchronously verify delivery route")
    delivery_args(probe)

    after = actions.add_parser("after", help="wake after duration")
    after.add_argument("duration", type=parse_duration)
    delivery_args(after)

    run = actions.add_parser("run", help="wake when command reaches terminal result")
    run.add_argument("--timeout", type=parse_duration, help="overall timeout across attempts")
    run.add_argument("--max-retries", type=nonnegative, default=0)
    run.add_argument("--retry-delay", type=parse_duration, default=30.0)
    delivery_args(run)
    run.add_argument("command", nargs=argparse.REMAINDER)

    actions.add_parser("list", help="list waits")
    status = actions.add_parser("status", help="show wait")
    status.add_argument("wait_id")
    cancel_parser = actions.add_parser("cancel", help="cancel wait")
    cancel_parser.add_argument("wait_id")
    worker_parser = actions.add_parser("_worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("wait_id")
    return parser


def main() -> int:
    os.umask(0o077)
    parser = build_parser()
    args = parser.parse_args()
    try:
        delivery = lambda: delivery_value(args.remote, args.remote_auth_token_env)
        if args.action == "probe":
            emit(register("probe", {}, args.message, delivery()))
        elif args.action == "after":
            spec: JsonObject = {"seconds": args.duration, "registered_at": time.time()}
            emit(register("after", spec, args.message, delivery()))
        elif args.action == "run":
            spec = {
                "command": command_value(args.command),
                "timeout": args.timeout,
                "max_retries": args.max_retries,
                "retry_delay": args.retry_delay,
            }
            emit(register("run", spec, args.message, delivery()))
        elif args.action == "list":
            records = [load_record(path.stem) for path in state_dir().glob("*.json")]
            records.sort(key=lambda item: float(cast(float, item["created_at"])), reverse=True)
            emit([public_record(record) for record in records])
        elif args.action == "status":
            emit(public_record(load_record(args.wait_id)))
        elif args.action == "cancel":
            emit(cancel(args.wait_id))
        elif args.action == "_worker":
            return worker(args.wait_id)
        return 0
    except Exception as error:
        print(f"{parser.prog}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

