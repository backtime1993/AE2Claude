"""Batch, task, cancellation, and event primitives for Agent clients."""
from __future__ import annotations

import copy
import inspect
import re
import threading
import time
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from .capabilities import AGENT_PROTOCOL
from .script_library import capture_method
from .runtime import (
    SafetyError,
    authorize,
    bridge,
    classify_bridge_method,
    public_bridge_methods,
    require_enabled,
)

_REFERENCE = re.compile(r"^\$(\d+)((?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*)$")
_PATH_TOKEN = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class EventLog:
    def __init__(self, capacity: int = 1000) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._sequence = 0
        self._condition = threading.Condition()

    def emit(self, event_type: str, **data: Any) -> dict[str, Any]:
        with self._condition:
            self._sequence += 1
            event = {
                "sequence": self._sequence,
                "time": _now(),
                "type": event_type,
                **data,
            }
            self._events.append(event)
            self._condition.notify_all()
            return copy.deepcopy(event)

    def read(self, after: int = 0, limit: int = 100, wait_ms: int = 0) -> dict[str, Any]:
        after = max(0, int(after))
        limit = max(1, min(int(limit), 500))
        wait_ms = max(0, min(int(wait_ms), 30_000))
        deadline = time.monotonic() + wait_ms / 1000
        with self._condition:
            while wait_ms and self._sequence <= after:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            events = [event for event in self._events if event["sequence"] > after]
            events = events[:limit]
            return {
                "ok": True,
                "protocol": AGENT_PROTOCOL,
                "after": after,
                "cursor": events[-1]["sequence"] if events else self._sequence,
                "events": copy.deepcopy(events),
            }


EVENTS = EventLog()


def _resolve_reference(text: str, results: list[Any]) -> Any:
    match = _REFERENCE.fullmatch(text)
    if not match:
        return text
    index = int(match.group(1))
    if index >= len(results):
        raise ValueError(f"result reference {text} is not available")
    value: Any = results[index]
    for token in _PATH_TOKEN.finditer(match.group(2)):
        key, item_index = token.groups()
        if key is not None:
            if not isinstance(value, dict) or key not in value:
                raise ValueError(f"result reference {text} has no field {key}")
            value = value[key]
        else:
            value = value[int(item_index)]
    return copy.deepcopy(value)


def resolve_references(value: Any, results: list[Any]) -> Any:
    if isinstance(value, str):
        return _resolve_reference(value, results)
    if isinstance(value, list):
        return [resolve_references(item, results) for item in value]
    if isinstance(value, dict):
        return {key: resolve_references(item, results) for key, item in value.items()}
    return value


def _validate_references(value: Any, operation_index: int) -> None:
    # Field names and array bounds depend on runtime results; ordering does not.
    if isinstance(value, str):
        match = _REFERENCE.fullmatch(value)
        if match and int(match.group(1)) >= operation_index:
            raise ValueError(
                f"operation {operation_index} reference {value} must target an earlier operation"
            )
    elif isinstance(value, list):
        for item in value:
            _validate_references(item, operation_index)
    elif isinstance(value, dict):
        for item in value.values():
            _validate_references(item, operation_index)


def _validate_operations(operations: list[dict[str, Any]], confirm: bool) -> list[dict[str, Any]]:
    if not isinstance(operations, list) or not 1 <= len(operations) <= 256:
        raise ValueError("batch must contain 1..256 operations")
    public = set(public_bridge_methods())
    normalized: list[dict[str, Any]] = []
    for index, source in enumerate(operations):
        if not isinstance(source, dict):
            raise ValueError(f"operation {index} must be an object")
        method = str(source.get("method", ""))
        if method not in public:
            raise ValueError(f"operation {index} uses unknown method: {method}")
        args = source.get("args", [])
        kwargs = source.get("kwargs", {})
        if not isinstance(args, list) or not isinstance(kwargs, dict):
            raise ValueError(f"operation {index} args/kwargs have invalid types")
        member = getattr(__import__("ae_bridge").AEBridge, method)
        try:
            inspect.signature(member).bind(None, *args, **kwargs)
        except TypeError as exc:
            raise ValueError(f"operation {index} ({method}) has invalid arguments: {exc}") from exc
        _validate_references(args, index)
        _validate_references(kwargs, index)
        risk = classify_bridge_method(method)
        authorize(risk, confirm=confirm)
        normalized.append({"method": method, "args": args, "kwargs": kwargs, "risk": risk})
    return normalized


def execute_batch(
    operations: list[dict[str, Any]],
    *,
    dry_run: bool = False,
    fail_fast: bool = True,
    confirm: bool = False,
    request_id: str | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    require_enabled()
    normalized = _validate_operations(operations, confirm)
    request_id = request_id or str(uuid.uuid4())
    started = time.perf_counter()
    EVENTS.emit("batch.started", requestId=request_id, operationCount=len(normalized), dryRun=dry_run)

    if dry_run:
        plan = []
        for item in normalized:
            member = getattr(__import__("ae_bridge").AEBridge, item["method"])
            plan.append({
                "method": item["method"],
                "risk": item["risk"],
                "signature": str(inspect.signature(member)),
            })
        result = {
            "ok": True,
            "protocol": AGENT_PROTOCOL,
            "requestId": request_id,
            "dryRun": True,
            "operationCount": len(normalized),
            "plan": plan,
        }
        EVENTS.emit("batch.completed", requestId=request_id, dryRun=True)
        return result

    raw_results: list[Any] = []
    entries: list[dict[str, Any]] = []
    has_writes = any(item["risk"] != "read" for item in normalized)
    cancelled = False
    stop_reason = None

    with bridge() as ae:
        for index, item in enumerate(normalized):
            if cancel_event and cancel_event.is_set():
                cancelled = True
                stop_reason = "cancel-requested"
                break
            try:
                require_enabled()
            except SafetyError:
                cancelled = True
                stop_reason = "disabled"
                break
            try:
                args = resolve_references(item["args"], raw_results)
                kwargs = resolve_references(item["kwargs"], raw_results)
                value = getattr(ae, item["method"])(*args, **kwargs)
                raw_results.append(value)
                entry = {"index": index, "ok": True, "result": value}
                captured = capture_method(item["method"], args, kwargs, value)
                if captured is not None:
                    entry["capture"] = captured
                entries.append(entry)
                EVENTS.emit(
                    "batch.operation.completed",
                    requestId=request_id,
                    index=index,
                    method=item["method"],
                )
            except Exception as exc:
                raw_results.append(None)
                entries.append({"index": index, "ok": False, "error": str(exc)})
                EVENTS.emit(
                    "batch.operation.failed",
                    requestId=request_id,
                    index=index,
                    method=item["method"],
                    error=str(exc),
                )
                if fail_fast:
                    break

    ok = not cancelled and len(entries) == len(normalized) and all(
        entry["ok"] for entry in entries
    )
    response = {
        "ok": ok,
        "protocol": AGENT_PROTOCOL,
        "requestId": request_id,
        "dryRun": False,
        "cancelled": cancelled,
        "stopReason": stop_reason,
        "operationCount": len(normalized),
        "completedCount": len(entries),
        "undoMode": "per-operation" if has_writes else "none",
        "singleUndoGroup": False,
        "durationMs": round((time.perf_counter() - started) * 1000, 3),
        "results": entries,
    }
    EVENTS.emit(
        "batch.cancelled" if cancelled else ("batch.completed" if ok else "batch.failed"),
        requestId=request_id,
        completedCount=len(entries),
    )
    return response


class JobManager:
    def __init__(self, max_pending: int = 32, ttl_ms: int = 900_000) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ae2claude-agent")
        self._max_pending = max_pending
        self._default_ttl = ttl_ms
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _cleanup(self) -> None:
        now = time.time()
        expired = [
            task_id
            for task_id, job in self._jobs.items()
            if job["terminalAt"] and now * 1000 - job["terminalAt"] > job["ttl"]
        ]
        for task_id in expired:
            del self._jobs[task_id]

    def submit(self, operations: list[dict[str, Any]], **options: Any) -> dict[str, Any]:
        # Validate safety and shape before returning a task ID.
        _validate_operations(operations, bool(options.get("confirm", False)))
        ttl = max(60_000, min(int(options.pop("ttl_ms", self._default_ttl)), 3_600_000))
        with self._lock:
            self._cleanup()
            active = sum(not job["terminalAt"] for job in self._jobs.values())
            if active >= self._max_pending:
                raise RuntimeError("agent job queue is full")
            task_id = str(uuid.uuid4())
            created = _now()
            cancel_event = threading.Event()
            job: dict[str, Any] = {
                "taskId": task_id,
                "status": "working",
                "statusMessage": "Queued for the AE main thread.",
                "createdAt": created,
                "lastUpdatedAt": created,
                "ttl": ttl,
                "pollInterval": 500,
                "terminalAt": None,
                "cancelEvent": cancel_event,
                "future": None,
                "result": None,
            }
            self._jobs[task_id] = job
            future = self._executor.submit(
                execute_batch,
                operations,
                request_id=task_id,
                cancel_event=cancel_event,
                **options,
            )
            job["future"] = future
        # A very small/dry-run task can finish synchronously. Registering the
        # callback while holding the manager lock would deadlock in that case.
        EVENTS.emit("task.created", taskId=task_id)
        future.add_done_callback(lambda done, current=task_id: self._finish(current, done))
        return self.get(task_id)

    def _finish(self, task_id: str, future: Future[Any]) -> None:
        with self._lock:
            job = self._jobs.get(task_id)
            if job is None:
                return
            try:
                result = future.result()
                status = "cancelled" if result.get("cancelled") else (
                    "completed" if result.get("ok") else "failed"
                )
                message = "Completed." if status == "completed" else (
                    "Cancelled between AE operations." if status == "cancelled" else "Batch failed."
                )
                job["result"] = result
            except Exception as exc:
                status = "cancelled" if future.cancelled() else "failed"
                message = "Cancelled before execution." if status == "cancelled" else str(exc)
                job["result"] = {"ok": False, "error": str(exc)}
            job["status"] = status
            job["statusMessage"] = message
            job["lastUpdatedAt"] = _now()
            job["terminalAt"] = int(time.time() * 1000)
        EVENTS.emit(f"task.{status}", taskId=task_id)

    @staticmethod
    def _public(job: dict[str, Any], include_result: bool = True) -> dict[str, Any]:
        output = {
            key: copy.deepcopy(value)
            for key, value in job.items()
            if key not in {"future", "cancelEvent", "terminalAt", "result"}
        }
        if include_result and job["status"] != "working":
            output["result"] = copy.deepcopy(job["result"])
        return output

    def get(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            self._cleanup()
            job = self._jobs.get(task_id)
            if job is None:
                raise KeyError(f"unknown task: {task_id}")
            return self._public(job)

    def list(self, limit: int = 50) -> dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        with self._lock:
            self._cleanup()
            jobs = list(self._jobs.values())[-limit:]
            return {"ok": True, "tasks": [self._public(job, False) for job in jobs]}

    def cancel(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(task_id)
            if job is None:
                raise KeyError(f"unknown task: {task_id}")
            if job["status"] != "working":
                return self._public(job)
            job["cancelEvent"].set()
            future: Future[Any] = job["future"]

        # Future.cancel() runs done callbacks synchronously. Calling it while
        # holding the manager lock would deadlock in _finish().
        cancelled_before_execution = future.cancel()
        with self._lock:
            job = self._jobs.get(task_id)
            if job is None:
                raise KeyError(f"unknown task: {task_id}")
            if job["status"] == "working":
                if cancelled_before_execution:
                    job["statusMessage"] = "Cancellation accepted before execution."
                else:
                    job["statusMessage"] = (
                        "Cancellation requested; current AE call cannot be preempted."
                    )
                job["lastUpdatedAt"] = _now()
            return self._public(job)


JOBS = JobManager()
