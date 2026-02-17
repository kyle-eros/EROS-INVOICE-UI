from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from .config import get_settings
from .models import (
    ArtifactListResponse,
    ConfirmResponse,
    PreviewRequest,
    PreviewResponse,
    RunOnceResponse,
    TaskDetail,
    TaskSummary,
)
from .store import InMemoryTaskStore, TaskNotFoundError

_settings = get_settings()
router = APIRouter(prefix=f"{_settings.api_prefix}/invoicing", tags=["invoicing"])
task_store = InMemoryTaskStore()


@router.post("/preview", response_model=PreviewResponse, status_code=status.HTTP_201_CREATED)
def preview_invoice(payload: PreviewRequest) -> PreviewResponse:
    record = task_store.create_preview(payload)
    return PreviewResponse(
        task_id=record.task_id,
        status=record.status,
        agent_slug=record.payload.agent_slug,
        mode=record.payload.mode,
        window_start=record.payload.window_start,
        window_end=record.payload.window_end,
        source_count=len(record.payload.source_refs),
        created_at=record.created_at,
    )


@router.post("/confirm/{task_id}", response_model=ConfirmResponse)
def confirm_invoice(task_id: str) -> ConfirmResponse:
    try:
        record = task_store.confirm(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}") from exc
    return ConfirmResponse(task_id=record.task_id, status=record.status)


@router.post("/run/once", response_model=RunOnceResponse)
def run_once() -> RunOnceResponse:
    task_ids = task_store.run_once()
    return RunOnceResponse(processed_count=len(task_ids), task_ids=task_ids)


@router.get("/tasks", response_model=list[TaskSummary])
def list_tasks() -> list[TaskSummary]:
    return task_store.list_tasks()


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def get_task(task_id: str) -> TaskDetail:
    try:
        return task_store.get_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}") from exc


@router.get("/artifacts/{task_id}", response_model=ArtifactListResponse)
def get_artifacts(task_id: str) -> ArtifactListResponse:
    try:
        return task_store.get_artifacts(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}") from exc
