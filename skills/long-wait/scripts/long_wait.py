#!/usr/bin/env python3
"""Wait outside agent turns, then queue input to originating Codex thread."""

from __future__ import annotations

import argparse
import atexit
import fcntl
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Iterator, List, Mapping, Optional, Union


class WaitKind(str, Enum):
    PROBE = "probe"
    AFTER = "after"
    RUN = "run"
    UNTIL = "until"


class WaitState(str, Enum):
    PENDING = "pending"
    WAITING = "waiting"
    READY = "ready"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    DELIVERY_UNKNOWN = "delivery_unknown"
    CANCELLED = "cancelled"
    FAILED = "failed"


def as_mapping(value: object, name: str) -> Dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object with string keys")
    return {str(key): item for key, item in value.items()}


def required_str(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def required_int(data: Mapping[str, object], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value


def required_float(data: Mapping[str, object], key: str) -> float:
    value = data.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{key} must be a number")
    return float(value)


def optional_str(data: Mapping[str, object], key: str) -> Optional[str]:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{key} must be a string or null")
    return value


def optional_int(data: Mapping[str, object], key: str) -> Optional[int]:
    value = data.get(key)
    if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
        raise ValueError(f"{key} must be an integer or null")
    return value


def optional_float(data: Mapping[str, object], key: str) -> Optional[float]:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{key} must be a number or null")
    return float(value)


@dataclass(frozen=True)
class AfterSpec:
    seconds: float
    registered_at: float

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> AfterSpec:
        return cls(
            seconds=required_float(data, "seconds"),
            registered_at=required_float(data, "registered_at"),
        )


@dataclass(frozen=True)
class RunSpec:
    command: List[str]
    timeout: Optional[float]
    max_retries: int
    retry_delay: float

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> RunSpec:
        command = data.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(item, str) for item in command)
        ):
            raise ValueError("command must be a nonempty string array")
        return cls(
            command=[item for item in command if isinstance(item, str)],
            timeout=optional_float(data, "timeout"),
            max_retries=required_int(data, "max_retries"),
            retry_delay=required_float(data, "retry_delay"),
        )


@dataclass(frozen=True)
class UntilSpec:
    command: List[str]
    timeout: float
    interval: float

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> UntilSpec:
        command = data.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(item, str) for item in command)
        ):
            raise ValueError("command must be a nonempty string array")
        return cls(
            command=[item for item in command if isinstance(item, str)],
            timeout=required_float(data, "timeout"),
            interval=required_float(data, "interval"),
        )


WaitSpec = Union[None, AfterSpec, RunSpec, UntilSpec]


@dataclass(frozen=True)
class WaitResult:
    kind: WaitKind
    status: int
    reason: Optional[str] = None
    attempts: Optional[int] = None
    checks: Optional[int] = None
    elapsed_seconds: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        value: Dict[str, object] = asdict(self)
        value["kind"] = self.kind.value
        return {key: item for key, item in value.items() if item is not None}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> WaitResult:
        return cls(
            kind=WaitKind(required_str(data, "kind")),
            status=required_int(data, "status"),
            reason=optional_str(data, "reason"),
            attempts=optional_int(data, "attempts"),
            checks=optional_int(data, "checks"),
            elapsed_seconds=optional_float(data, "elapsed_seconds"),
            error=optional_str(data, "error"),
        )


@dataclass
class WaitRecord:
    id: str
    thread_id: str
    kind: WaitKind
    spec: WaitSpec
    message: str
    delivery_assumption: str
    state: WaitState
    created_at: float
    log_path: str
    description: Optional[str] = None
    pid: Optional[int] = None
    child_pid: Optional[int] = None
    result: Optional[WaitResult] = None
    error: Optional[str] = None
    condition_at: Optional[float] = None
    delivered_at: Optional[float] = None

    def to_dict(self) -> Dict[str, object]:
        value: Dict[str, object] = asdict(self)
        value["kind"] = self.kind.value
        value["state"] = self.state.value
        value["result"] = self.result.to_dict() if self.result else None
        return value

    def public_dict(self) -> Dict[str, object]:
        value = self.to_dict()
        value["worker_alive"] = process_alive(self.pid)
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> WaitRecord:
        kind = WaitKind(required_str(data, "kind"))
        raw_spec = data.get("spec")
        if kind == WaitKind.PROBE:
            spec: WaitSpec = None
        elif kind == WaitKind.AFTER:
            spec = AfterSpec.from_dict(as_mapping(raw_spec, "spec"))
        elif kind == WaitKind.RUN:
            spec = RunSpec.from_dict(as_mapping(raw_spec, "spec"))
        else:
            spec = UntilSpec.from_dict(as_mapping(raw_spec, "spec"))
        raw_result = data.get("result")
        result = (
            None
            if raw_result is None
            else WaitResult.from_dict(as_mapping(raw_result, "result"))
        )
        return cls(
            id=required_str(data, "id"),
            thread_id=required_str(data, "thread_id"),
            kind=kind,
            spec=spec,
            message=required_str(data, "message"),
            delivery_assumption=required_str(data, "delivery_assumption"),
            state=WaitState(required_str(data, "state")),
            pid=optional_int(data, "pid"),
            child_pid=optional_int(data, "child_pid"),
            created_at=required_float(data, "created_at"),
            condition_at=optional_float(data, "condition_at"),
            delivered_at=optional_float(data, "delivered_at"),
            log_path=required_str(data, "log_path"),
            description=optional_str(data, "description"),
            result=result,
            error=optional_str(data, "error"),
        )


class WaitStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    @staticmethod
    def _checked_id(wait_id: str) -> str:
        return str(uuid.UUID(wait_id))

    def _record_path(self, wait_id: str) -> Path:
        return self.root / f"{self._checked_id(wait_id)}.json"

    @contextmanager
    def _lock(self, wait_id: str) -> Iterator[None]:
        path = self.root / f"{self._checked_id(wait_id)}.lock"
        with path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _load_unlocked(self, wait_id: str) -> WaitRecord:
        path = self._record_path(wait_id)
        if not path.exists():
            raise UnknownWaitError(f"unknown wait ID: {wait_id}")
        raw: object = json.loads(path.read_text())
        return WaitRecord.from_dict(as_mapping(raw, "wait record"))

    def _save_unlocked(self, record: WaitRecord) -> None:
        path = self._record_path(record.id)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n"
        )
        os.replace(temporary, path)

    def create(self, record: WaitRecord) -> None:
        with self._lock(record.id):
            if self._record_path(record.id).exists():
                raise RuntimeError(f"wait already exists: {record.id}")
            self._save_unlocked(record)

    def load(self, wait_id: str) -> WaitRecord:
        with self._lock(wait_id):
            return self._load_unlocked(wait_id)

    @contextmanager
    def edit(self, wait_id: str) -> Iterator[WaitRecord]:
        with self._lock(wait_id):
            record = self._load_unlocked(wait_id)
            yield record
            self._save_unlocked(record)

    def list(self) -> List[WaitRecord]:
        records = []
        for path in self.root.glob("*.json"):
            try:
                records.append(self.load(path.stem))
            except UnknownWaitError:
                continue
        records.sort(key=lambda record: record.created_at, reverse=True)
        return records

    def consume_delivered(self, wait_id: str) -> None:
        lock_path = self.root / f"{wait_id}.lock"
        with self._lock(wait_id):
            try:
                record = self._load_unlocked(wait_id)
            except UnknownWaitError:
                record = None
            if record is not None:
                if record.state != WaitState.DELIVERED:
                    return
                self._record_path(wait_id).unlink()
                log_path = self.root / f"{wait_id}.log"
                if log_path.exists() and (
                    record.kind == WaitKind.PROBE or log_path.stat().st_size == 0
                ):
                    log_path.unlink()
        lock_path.unlink(missing_ok=True)

    def cleanup(self, wait_id: str) -> List[str]:
        wait_id = self._checked_id(wait_id)
        lock_path = self.root / f"{wait_id}.lock"
        lock_existed = lock_path.exists()
        removed: List[str] = []
        with self._lock(wait_id):
            try:
                record = self._load_unlocked(wait_id)
            except UnknownWaitError:
                record = None
            if record is not None and record.state != WaitState.DELIVERED:
                cleanable = {WaitState.CANCELLED, WaitState.FAILED}
                if record.state not in cleanable:
                    raise RuntimeError(
                        f"cannot clean wait in state {record.state.value}"
                    )
                if record.state == WaitState.CANCELLED and process_alive(record.pid):
                    raise RuntimeError(
                        "cannot clean cancelled wait while worker is alive"
                    )
            for suffix in ("json", "log"):
                path = self.root / f"{wait_id}.{suffix}"
                if path.exists():
                    path.unlink()
                    removed.append(path.name)
        lock_path.unlink(missing_ok=True)
        if lock_existed:
            removed.append(lock_path.name)
        return removed


class UnknownWaitError(ValueError):
    pass


class RpcError(RuntimeError):
    pass


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
                "clientInfo": {
                    "name": "long_wait",
                    "title": "Long Wait",
                    "version": "0.3.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        self.send({"method": "initialized"})

    def send(self, message: Mapping[str, object]) -> None:
        if self.process.stdin is None:
            raise RuntimeError("app-server stdin unavailable")
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def call(self, method: str, params: Mapping[str, object]) -> Dict[str, object]:
        request_id = self.next_id
        self.next_id += 1
        self.send({"id": request_id, "method": method, "params": dict(params)})
        if self.process.stdout is None:
            raise RuntimeError("app-server stdout unavailable")
        while line := self.process.stdout.readline():
            raw: object = json.loads(line)
            response = as_mapping(raw, "app-server response")
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise RpcError(f"{method}: {response['error']}")
            return as_mapping(response.get("result"), f"{method} result")
        raise RuntimeError(f"app-server closed during {method}")

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=2)


def codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def process_alive(pid: Optional[int]) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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


def command_value(values: List[str]) -> List[str]:
    command = values[1:] if values[:1] == ["--"] else values
    if not command:
        raise ValueError("command required after --")
    return command


def preflight(thread_id: str) -> str:
    client: Optional[AppServerClient] = None
    try:
        client = AppServerClient()
        response = client.call(
            "thread/read", {"threadId": thread_id, "includeTurns": False}
        )
        thread = as_mapping(response.get("thread"), "thread")
        source = thread.get("source")
        if thread.get("ephemeral"):
            raise RuntimeError("ephemeral thread cannot receive durable input")
        if (
            thread.get("parentThreadId")
            or thread.get("threadSource") == "subagent"
            or isinstance(source, dict)
            and "subAgent" in source
        ):
            raise RuntimeError("primary agent required")
    except RpcError as error:
        raise RuntimeError(
            f"local preflight failed ({error}); check local daemon and CODEX_HOME"
        ) from error
    finally:
        if client:
            client.close()
    return "Standalone Codex or default local daemon shares host and CODEX_HOME. Durable primary thread verified."


def queue_message(record: WaitRecord) -> subprocess.CompletedProcess[str]:
    codex = os.environ.get("CODEX_BIN") or shutil.which("codex")
    if not codex:
        raise RuntimeError("codex executable not found; set CODEX_BIN")
    if record.result is None:
        raise RuntimeError("wait result missing")
    payload = {
        "id": record.id,
        "message": record.message,
        "status": record.result.status,
        "result": record.result.to_dict(),
    }
    if record.description:
        payload["description"] = record.description
    log_path = Path(record.log_path)
    if log_path.exists() and log_path.stat().st_size:
        payload["log_path"] = record.log_path
    marker = (
        "[long-wait-probe:v1]" if record.kind == WaitKind.PROBE else "[long-wait:v1]"
    )
    message = marker + " " + json.dumps(payload, separators=(",", ":"), sort_keys=True)
    command = [codex, "queue", "--thread", record.thread_id, "--message", message]
    return subprocess.run(
        command, check=False, capture_output=True, text=True, timeout=30
    )


def deliver(store: WaitStore, wait_id: str) -> None:
    with store.edit(wait_id) as record:
        if record.state != WaitState.READY:
            raise RuntimeError("wait not ready for delivery")
        record.state = WaitState.DELIVERING
        record.error = None
    delivered = False
    try:
        result = queue_message(store.load(wait_id))
        with store.edit(wait_id) as record:
            if record.state != WaitState.DELIVERING:
                return
            if result.returncode:
                record.state = WaitState.DELIVERY_UNKNOWN
                record.error = (
                    result.stderr.strip()
                    or result.stdout.strip()
                    or f"codex queue exited {result.returncode}"
                )
            else:
                record.state = WaitState.DELIVERED
                record.delivered_at = time.time()
                delivered = True
    except Exception as error:
        with store.edit(wait_id) as record:
            if record.state == WaitState.DELIVERING:
                record.state = WaitState.DELIVERY_UNKNOWN
                record.error = str(error)
    if delivered:
        atexit.register(store.consume_delivered, wait_id)


def spawn_worker(wait_id: str, log_path: Path) -> int:
    with log_path.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_worker", wait_id],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    return process.pid


def register(
    store: WaitStore,
    kind: WaitKind,
    spec: WaitSpec,
    message: str,
    description: Optional[str],
) -> WaitRecord:
    thread_id = os.environ.get("CODEX_THREAD_ID")
    if not thread_id:
        raise RuntimeError(
            "CODEX_THREAD_ID unavailable; register from Codex tool command"
        )
    assumption = preflight(thread_id)
    wait_id = str(uuid.uuid4())
    record = WaitRecord(
        id=wait_id,
        thread_id=thread_id,
        kind=kind,
        spec=spec,
        message=message,
        delivery_assumption=assumption,
        state=WaitState.PENDING,
        created_at=time.time(),
        log_path=str(store.root / f"{wait_id}.log"),
        description=description,
    )
    store.create(record)
    if kind == WaitKind.PROBE:
        with store.edit(wait_id) as editable:
            editable.state = WaitState.READY
            editable.result = WaitResult(kind=WaitKind.PROBE, status=0)
        deliver(store, wait_id)
        record = store.load(wait_id)
        if record.state != WaitState.DELIVERED:
            raise RuntimeError(
                f"probe {wait_id} not accepted: {record.state.value}: {record.error}"
            )
    else:
        try:
            pid = spawn_worker(wait_id, Path(record.log_path))
            with store.edit(wait_id) as editable:
                editable.pid = pid
        except Exception as error:
            with store.edit(wait_id) as editable:
                editable.state = WaitState.FAILED
                editable.error = str(error)
            raise
    return store.load(wait_id)


def cancelled(store: WaitStore, wait_id: str) -> bool:
    return store.load(wait_id).state == WaitState.CANCELLED


def sleep_until(store: WaitStore, wait_id: str, deadline: float) -> bool:
    while time.time() < deadline:
        if cancelled(store, wait_id):
            return False
        time.sleep(min(1, max(0, deadline - time.time())))
    return True


def after_result(
    store: WaitStore, wait_id: str, spec: AfterSpec
) -> Optional[WaitResult]:
    if not sleep_until(store, wait_id, spec.registered_at + spec.seconds):
        return None
    return WaitResult(kind=WaitKind.AFTER, status=0, elapsed_seconds=spec.seconds)


def stop_process(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def timeout_result(started: float, attempts: int) -> WaitResult:
    return WaitResult(
        kind=WaitKind.RUN,
        status=124,
        reason="timeout",
        attempts=attempts,
        elapsed_seconds=round(time.time() - started, 3),
    )


def run_result(store: WaitStore, wait_id: str, spec: RunSpec) -> Optional[WaitResult]:
    started = time.time()
    deadline = started + spec.timeout if spec.timeout is not None else None
    attempts = 0
    for _ in range(spec.max_retries + 1):
        if cancelled(store, wait_id):
            return None
        if deadline is not None and time.time() >= deadline:
            return timeout_result(started, attempts)
        attempts += 1
        process = subprocess.Popen(spec.command, start_new_session=True)
        with store.edit(wait_id) as record:
            record.child_pid = process.pid
        while process.poll() is None:
            if cancelled(store, wait_id):
                stop_process(process)
                return None
            if deadline is not None and time.time() >= deadline:
                stop_process(process)
                with store.edit(wait_id) as record:
                    record.child_pid = None
                return timeout_result(started, attempts)
            time.sleep(0.5)
        with store.edit(wait_id) as record:
            record.child_pid = None
        code = process.returncode
        status = code if code >= 0 else 128 - code
        if status == 0 or attempts > spec.max_retries:
            return WaitResult(
                kind=WaitKind.RUN,
                status=status,
                reason="exited" if status == 0 else "retries_exhausted",
                attempts=attempts,
                elapsed_seconds=round(time.time() - started, 3),
            )
        retry_deadline = time.time() + spec.retry_delay
        if deadline is not None:
            retry_deadline = min(retry_deadline, deadline)
        if not sleep_until(store, wait_id, retry_deadline):
            return None
    raise AssertionError("unreachable")


def until_result(
    store: WaitStore, wait_id: str, spec: UntilSpec
) -> Optional[WaitResult]:
    started = time.time()
    deadline = started + spec.timeout
    checks = 0
    while True:
        if cancelled(store, wait_id):
            return None
        if time.time() >= deadline:
            return WaitResult(
                kind=WaitKind.UNTIL,
                status=124,
                reason="timeout",
                checks=checks,
                elapsed_seconds=round(time.time() - started, 3),
            )
        checks += 1
        process = subprocess.Popen(spec.command, start_new_session=True)
        with store.edit(wait_id) as record:
            record.child_pid = process.pid
        while process.poll() is None:
            if cancelled(store, wait_id):
                stop_process(process)
                return None
            if time.time() >= deadline:
                stop_process(process)
                with store.edit(wait_id) as record:
                    record.child_pid = None
                return WaitResult(
                    kind=WaitKind.UNTIL,
                    status=124,
                    reason="timeout",
                    checks=checks,
                    elapsed_seconds=round(time.time() - started, 3),
                )
            time.sleep(0.5)
        with store.edit(wait_id) as record:
            record.child_pid = None
        code = process.returncode
        status = code if code >= 0 else 128 - code
        if status != 1:
            return WaitResult(
                kind=WaitKind.UNTIL,
                status=status,
                reason="condition_met" if status == 0 else "predicate_failed",
                checks=checks,
                elapsed_seconds=round(time.time() - started, 3),
            )
        if not sleep_until(store, wait_id, min(time.time() + spec.interval, deadline)):
            return None


def worker(store: WaitStore, wait_id: str) -> int:
    with store.edit(wait_id) as record:
        if record.state != WaitState.PENDING:
            return 0
        record.state = WaitState.WAITING
        record.pid = os.getpid()
    record = store.load(wait_id)
    try:
        if isinstance(record.spec, AfterSpec):
            result = after_result(store, wait_id, record.spec)
        elif isinstance(record.spec, RunSpec):
            result = run_result(store, wait_id, record.spec)
        elif isinstance(record.spec, UntilSpec):
            result = until_result(store, wait_id, record.spec)
        else:
            raise RuntimeError("worker wait spec missing")
    except Exception as error:
        result = WaitResult(
            kind=record.kind,
            status=125,
            reason="helper_error",
            error=str(error),
        )
    if result is None:
        return 0
    with store.edit(wait_id) as editable:
        if editable.state != WaitState.WAITING:
            return 0
        editable.state = WaitState.READY
        editable.result = result
        editable.condition_at = time.time()
    deliver(store, wait_id)
    return 0


def cancel(store: WaitStore, wait_id: str) -> WaitRecord:
    with store.edit(wait_id) as record:
        if record.state in {WaitState.DELIVERED, WaitState.CANCELLED}:
            return record
        record.state = WaitState.CANCELLED
        record.error = "cancelled"
    return store.load(wait_id)


def resolve(
    store: WaitStore,
    wait_id: str,
    resolution: str,
    accept_duplicate_risk: bool,
) -> WaitRecord:
    record = store.load(wait_id)
    if record.state != WaitState.DELIVERY_UNKNOWN:
        raise ValueError("only delivery_unknown waits can be resolved")
    if resolution == "delivered":
        with store.edit(wait_id) as current:
            if current.state != WaitState.DELIVERY_UNKNOWN:
                raise ValueError("wait state changed during resolution")
            current.state = WaitState.DELIVERED
            current.delivered_at = time.time()
            current.error = None
            record = current
        store.consume_delivered(wait_id)
        return record
    if not accept_duplicate_risk:
        raise ValueError("retry requires --accept-duplicate-risk")
    preflight(thread_id=record.thread_id)
    with store.edit(wait_id) as current:
        if current.state != WaitState.DELIVERY_UNKNOWN:
            raise ValueError("wait state changed during resolution")
        current.state = WaitState.READY
        current.error = None
    deliver(store, wait_id)
    return store.load(wait_id)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        parts = ((days, "d"), (hours, "h"), (minutes, "m"))
    elif hours:
        parts = ((hours, "h"), (minutes, "m"))
    elif minutes:
        parts = ((minutes, "m"), (seconds, "s"))
    else:
        parts = ((seconds, "s"),)
    return "".join(f"{value}{suffix}" for value, suffix in parts if value) or "0s"


def format_description(description: Optional[str]) -> str:
    value = " ".join(description.split()) if description else ""
    return value if len(value) <= 48 else value[:47] + "…"


def format_record(record: WaitRecord, heading: str) -> str:
    lines = [
        heading,
        f"  ID: {record.id}",
        f"  Kind: {record.kind.value}",
        f"  State: {record.state.value}",
        f"  Thread: {record.thread_id}",
        f"  Age: {format_duration(time.time() - record.created_at)}",
        f"  Worker: {'alive' if process_alive(record.pid) else '-'}",
        f"  Description: {record.description or '-'}",
    ]
    if isinstance(record.spec, AfterSpec):
        lines.append(f"  Delay: {format_duration(record.spec.seconds)}")
    elif isinstance(record.spec, RunSpec):
        lines.extend(
            (
                f"  Command: {shlex.join(record.spec.command)}",
                f"  Timeout: {format_duration(record.spec.timeout) if record.spec.timeout is not None else '-'}",
                f"  Max retries: {record.spec.max_retries}",
                f"  Retry delay: {format_duration(record.spec.retry_delay)}",
            )
        )
    elif isinstance(record.spec, UntilSpec):
        lines.extend(
            (
                f"  Predicate: {shlex.join(record.spec.command)}",
                f"  Timeout: {format_duration(record.spec.timeout)}",
                f"  Interval: {format_duration(record.spec.interval)}",
            )
        )
    if record.result is not None:
        result = record.result.to_dict()
        lines.append(
            "  Result: " + ", ".join(f"{key}={value}" for key, value in result.items())
        )
    if record.error:
        lines.append(f"  Error: {record.error}")
    lines.extend(
        (
            f"  Message: {record.message}",
            f"  Delivery assumption: {record.delivery_assumption}",
        )
    )
    return "\n".join(lines)


def format_waits(
    records: List[WaitRecord], total: int, thread_id: Optional[str]
) -> str:
    if thread_id is None:
        header = f"All waits on current machine ({len(records)}):"
    else:
        header = f"Waits of current thread {thread_id} ({len(records)}/{total}):"
    if not records:
        return f"{header}\nNo waits."
    rows = [("ID", "KIND", "STATE", "AGE/LIMIT", "WORKER", "DESCRIPTION")]
    now = time.time()
    for record in records:
        worker = "alive" if process_alive(record.pid) else "-"
        age = format_duration(now - record.created_at)
        if isinstance(record.spec, AfterSpec):
            limit = record.spec.seconds
        elif isinstance(record.spec, RunSpec):
            limit = record.spec.timeout
        elif isinstance(record.spec, UntilSpec):
            limit = record.spec.timeout
        else:
            limit = None
        age_limit = f"{age}/{format_duration(limit)}" if limit is not None else age
        rows.append(
            (
                record.id,
                record.kind.value,
                record.state.value,
                age_limit,
                worker,
                format_description(record.description) or "-",
            )
        )
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    table = "\n".join(
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in rows
    )
    return f"{header}\n{table}"


def print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def print_record(record: WaitRecord, json_output: bool, heading: str) -> None:
    if json_output:
        print_json(record.public_dict())
    else:
        print(format_record(record, heading))


def print_action(record: WaitRecord, json_output: bool, action: str) -> None:
    if json_output:
        print_json(record.public_dict())
    else:
        print(f"{action} {record.id}: state={record.state.value}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wait independently, then continue current Codex thread."
    )
    actions = parser.add_subparsers(dest="action", required=True)
    default_message = "Long wait reached a terminal result. Continue prior task using attached result."

    def delivery_args(value: argparse.ArgumentParser) -> None:
        value.add_argument(
            "--message",
            default=default_message,
            help="continuation note in wake envelope",
        )
        value.add_argument(
            "--description",
            help="human-facing description of the wait",
        )

    def json_arg(value: argparse.ArgumentParser) -> None:
        value.add_argument("--json", action="store_true", help="emit full JSON output")

    probe = actions.add_parser("probe", help="synchronously verify delivery route")
    delivery_args(probe)
    json_arg(probe)

    after = actions.add_parser("after", help="wake after duration")
    after.add_argument("duration", type=parse_duration)
    delivery_args(after)
    json_arg(after)

    run = actions.add_parser("run", help="wake when command reaches terminal result")
    run.add_argument(
        "--timeout", type=parse_duration, help="overall timeout across attempts"
    )
    run.add_argument("--max-retries", type=nonnegative, default=0)
    run.add_argument("--retry-delay", type=parse_duration, default=30.0)
    delivery_args(run)
    json_arg(run)
    run.add_argument("command", nargs=argparse.REMAINDER)

    until = actions.add_parser(
        "until", help="wake when a predicate reaches terminal result"
    )
    until.add_argument("--timeout", type=parse_duration, required=True)
    until.add_argument("--interval", type=parse_duration, default=30.0)
    delivery_args(until)
    json_arg(until)
    until.add_argument("command", nargs=argparse.REMAINDER)

    list_parser = actions.add_parser("list", help="list waits")
    list_parser.add_argument(
        "--all",
        action="store_true",
        dest="all_waits",
        help="include waits from all threads",
    )
    json_arg(list_parser)
    status = actions.add_parser("status", help="show wait")
    status.add_argument("wait_id")
    json_arg(status)
    cancel_parser = actions.add_parser("cancel", help="cancel wait")
    cancel_parser.add_argument("wait_id")
    json_arg(cancel_parser)
    resolve_parser = actions.add_parser("resolve", help="resolve ambiguous delivery")
    resolve_parser.add_argument("wait_id")
    resolve_parser.add_argument("resolution", choices=("delivered", "retry"))
    resolve_parser.add_argument("--accept-duplicate-risk", action="store_true")
    json_arg(resolve_parser)
    cleanup_parser = actions.add_parser(
        "cleanup", help="remove artifacts for a delivered wait"
    )
    cleanup_parser.add_argument("wait_id")
    json_arg(cleanup_parser)
    worker_parser = actions.add_parser("_worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("wait_id")
    return parser


def main() -> int:
    os.umask(0o077)
    parser = build_parser()
    args = parser.parse_args()
    store = WaitStore(codex_home() / "long-waits")
    try:
        if args.action == "probe":
            record = register(
                store,
                WaitKind.PROBE,
                None,
                args.message,
                args.description,
            )
            print_record(record, args.json, "Wait registered:")
        elif args.action == "after":
            record = register(
                store,
                WaitKind.AFTER,
                AfterSpec(seconds=args.duration, registered_at=time.time()),
                args.message,
                args.description,
            )
            print_record(record, args.json, "Wait registered:")
        elif args.action == "run":
            record = register(
                store,
                WaitKind.RUN,
                RunSpec(
                    command=command_value(args.command),
                    timeout=args.timeout,
                    max_retries=args.max_retries,
                    retry_delay=args.retry_delay,
                ),
                args.message,
                args.description,
            )
            print_record(record, args.json, "Wait registered:")
        elif args.action == "until":
            record = register(
                store,
                WaitKind.UNTIL,
                UntilSpec(
                    command=command_value(args.command),
                    timeout=args.timeout,
                    interval=args.interval,
                ),
                args.message,
                args.description,
            )
            print_record(record, args.json, "Wait registered:")
        elif args.action == "list":
            all_records = store.list()
            thread_id = None if args.all_waits else os.environ.get("CODEX_THREAD_ID")
            records = (
                all_records
                if thread_id is None
                else [record for record in all_records if record.thread_id == thread_id]
            )
            if args.json:
                print_json([record.public_dict() for record in records])
            else:
                print(format_waits(records, len(all_records), thread_id))
        elif args.action == "status":
            print_record(store.load(args.wait_id), args.json, "Wait status:")
        elif args.action == "cancel":
            print_action(cancel(store, args.wait_id), args.json, "Cancelled")
        elif args.action == "resolve":
            record = resolve(
                store, args.wait_id, args.resolution, args.accept_duplicate_risk
            )
            print_action(record, args.json, f"Resolved ({args.resolution})")
        elif args.action == "cleanup":
            removed = store.cleanup(args.wait_id)
            if args.json:
                print_json({"id": args.wait_id, "removed": removed})
            else:
                print(
                    "Removed: " + ", ".join(removed)
                    if removed
                    else "Nothing to remove."
                )
        elif args.action == "_worker":
            return worker(store, args.wait_id)
        return 0
    except Exception as error:
        print(f"{parser.prog}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
