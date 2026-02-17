from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import count
from threading import Lock

from .models import Artifact, ArtifactListResponse, PreviewRequest, TaskDetail, TaskSummary

class TaskNotFoundError(KeyError):
    """Raised when an operation references a task id that does not exist."""


@dataclass
class _TaskRecord:
    task_id: str
    status: str
    payload: PreviewRequest
    created_at: datetime
    updated_at: datetime


class InMemoryTaskStore:
    """Deterministic in-memory store with incremental task ids."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counter = count(1)
        self._tasks: dict[str, _TaskRecord] = {}
        self._artifacts: dict[str, list[Artifact]] = {}
        self._idempotency_index: dict[str, str] = {}

    def reset(self) -> None:
        with self._lock:
            self._counter = count(1)
            self._tasks.clear()
            self._artifacts.clear()
            self._idempotency_index.clear()

    def create_preview(self, payload: PreviewRequest) -> _TaskRecord:
        with self._lock:
            idem = payload.idempotency_key
            if idem:
                existing_task_id = self._idempotency_index.get(idem)
                if existing_task_id is not None:
                    existing_record = self._tasks.get(existing_task_id)
                    if existing_record is not None:
                        return existing_record

            now = datetime.now(timezone.utc)
            task_id = f"task-{next(self._counter):04d}"
            record = _TaskRecord(
                task_id=task_id,
                status="previewed",
                payload=payload,
                created_at=now,
                updated_at=now,
            )
            self._tasks[task_id] = record
            self._artifacts[task_id] = []
            if idem:
                self._idempotency_index[idem] = task_id
            return record

    def confirm(self, task_id: str) -> _TaskRecord:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                raise TaskNotFoundError(task_id)
            if record.status == "previewed":
                record.status = "confirmed"
                record.updated_at = datetime.now(timezone.utc)
            return record

    def run_once(self) -> list[str]:
        processed: list[str] = []
        with self._lock:
            for task_id in sorted(self._tasks):
                record = self._tasks[task_id]
                if record.status != "confirmed":
                    continue
                record.status = "completed"
                record.updated_at = datetime.now(timezone.utc)
                self._artifacts[task_id] = [self._build_artifact(record)]
                processed.append(task_id)
        return processed

    def list_tasks(self) -> list[TaskSummary]:
        with self._lock:
            return [self._to_summary(self._tasks[task_id]) for task_id in sorted(self._tasks)]

    def get_task(self, task_id: str) -> TaskDetail:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                raise TaskNotFoundError(task_id)
            return self._to_detail(record)

    def get_artifacts(self, task_id: str) -> ArtifactListResponse:
        with self._lock:
            if task_id not in self._tasks:
                raise TaskNotFoundError(task_id)
            return ArtifactListResponse(
                task_id=task_id,
                artifacts=list(self._artifacts.get(task_id, [])),
            )

    def _build_artifact(self, record: _TaskRecord) -> Artifact:
        payload = record.payload
        lines = [
            f"task_id={record.task_id}",
            f"agent_slug={payload.agent_slug}",
            f"mode={payload.mode}",
            f"window_start={payload.window_start.isoformat()}",
            f"window_end={payload.window_end.isoformat()}",
            f"source_count={len(payload.source_refs)}",
            f"idempotency_key={payload.idempotency_key or ''}",
            f"principal_employee_id={payload.principal_employee_id or ''}",
        ]
        for index, source_ref in enumerate(payload.source_refs, start=1):
            lines.append(f"source_ref_{index}={source_ref}")
        for key in sorted(payload.metadata):
            lines.append(f"metadata.{key}={payload.metadata[key]}")
        return Artifact(
            filename=f"invoicing-task-{record.task_id}.txt",
            content_type="text/plain",
            content="\n".join(lines),
        )

    def _to_summary(self, record: _TaskRecord) -> TaskSummary:
        payload = record.payload
        return TaskSummary(
            task_id=record.task_id,
            status=record.status,
            agent_slug=payload.agent_slug,
            mode=payload.mode,
            window_start=payload.window_start,
            window_end=payload.window_end,
            source_count=len(payload.source_refs),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _to_detail(self, record: _TaskRecord) -> TaskDetail:
        payload = record.payload
        return TaskDetail(
            task_id=record.task_id,
            status=record.status,
            agent_slug=payload.agent_slug,
            mode=payload.mode,
            window_start=payload.window_start,
            window_end=payload.window_end,
            source_refs=list(payload.source_refs),
            idempotency_key=payload.idempotency_key,
            principal_employee_id=payload.principal_employee_id,
            metadata=dict(payload.metadata),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
