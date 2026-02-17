from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

TaskStatus = Literal["previewed", "confirmed", "completed"]
RunMode = Literal["plan_only", "dry_run"]
FinancialAgentSlug = Literal[
    "payout-reconciliation",
    "commission-payroll",
    "chargeback-defense",
]


class PreviewRequest(BaseModel):
    agent_slug: FinancialAgentSlug
    window_start: date
    window_end: date
    source_refs: list[str] = Field(min_length=1, max_length=256)
    mode: RunMode = "plan_only"
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=256)
    principal_employee_id: str | None = Field(default=None, min_length=1, max_length=128)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("source_refs")
    @classmethod
    def _normalize_source_refs(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_ref in value:
            source_ref = str(raw_ref).strip()
            if not source_ref:
                raise ValueError("source_refs entries cannot be blank")
            if source_ref in seen:
                raise ValueError("source_refs entries must be unique")
            seen.add(source_ref)
            normalized.append(source_ref)
        return normalized

    @field_validator("metadata")
    @classmethod
    def _normalize_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_key, raw_item in value.items():
            key = str(raw_key).strip()
            item = str(raw_item).strip()
            if not key:
                raise ValueError("metadata keys cannot be blank")
            if not item:
                raise ValueError("metadata values cannot be blank")
            normalized[key] = item
        return normalized

    @model_validator(mode="after")
    def _validate_window(self) -> PreviewRequest:
        if self.window_end < self.window_start:
            raise ValueError("window_end must be greater than or equal to window_start")
        return self


class PreviewResponse(BaseModel):
    task_id: str
    status: TaskStatus
    agent_slug: FinancialAgentSlug
    mode: RunMode
    window_start: date
    window_end: date
    source_count: int
    created_at: datetime


class ConfirmResponse(BaseModel):
    task_id: str
    status: TaskStatus


class RunOnceResponse(BaseModel):
    processed_count: int
    task_ids: list[str]


class TaskSummary(BaseModel):
    task_id: str
    status: TaskStatus
    agent_slug: FinancialAgentSlug
    mode: RunMode
    window_start: date
    window_end: date
    source_count: int
    created_at: datetime
    updated_at: datetime


class TaskDetail(BaseModel):
    task_id: str
    status: TaskStatus
    agent_slug: FinancialAgentSlug
    mode: RunMode
    window_start: date
    window_end: date
    source_refs: list[str]
    idempotency_key: str | None = None
    principal_employee_id: str | None = None
    metadata: dict[str, str]
    created_at: datetime
    updated_at: datetime


class Artifact(BaseModel):
    filename: str
    content_type: str
    content: str


class ArtifactListResponse(BaseModel):
    task_id: str
    artifacts: list[Artifact]
