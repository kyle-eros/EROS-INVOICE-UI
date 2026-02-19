from __future__ import annotations

import pickle
import re
from datetime import datetime, timezone
from itertools import count
from typing import Callable

from .store import InMemoryTaskStore

SQLALCHEMY_AVAILABLE = True
try:
    from sqlalchemy import DateTime, LargeBinary, String, create_engine
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
except ModuleNotFoundError:
    SQLALCHEMY_AVAILABLE = False


if SQLALCHEMY_AVAILABLE:

    class InvoiceStoreBase(DeclarativeBase):
        pass


    class _TaskStoreStateRow(InvoiceStoreBase):
        __tablename__ = "task_store_state"

        store_key: Mapped[str] = mapped_column(String(64), primary_key=True)
        payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
        updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

else:

    class _InvoiceStoreBaseStub:
        metadata = None


    InvoiceStoreBase = _InvoiceStoreBaseStub()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


_COUNT_TYPE = type(count())
_COUNT_RE = re.compile(r"^count\((-?\d+)(?:,\s*(-?\d+))?\)$")


def _serialize_count(value) -> dict[str, list[int]]:
    match = _COUNT_RE.match(repr(value))
    if match is None:
        raise RuntimeError("unable to serialize counter state")
    start = int(match.group(1))
    step = int(match.group(2) or "1")
    return {"__counter__": [start, step]}


class SqlAlchemyTaskStore(InMemoryTaskStore):
    _STORE_KEY = "default"
    _NON_PERSISTED_ATTRS = {"_lock", "_engine", "_session_factory"}
    _PERSISTING_METHODS = (
        "reset",
        "revoke_broker_token",
        "check_and_record_reminder_trigger",
        "create_preview",
        "confirm",
        "run_once",
        "upsert_invoices",
        "dispatch_invoice",
        "acknowledge_dispatch",
        "submit_creator_payment_submission",
        "create_checkout_session",
        "apply_payment_webhook",
        "resolve_reconciliation_case",
        "apply_payment_event",
        "apply_reminder_attempt_outcome",
        "run_reminders",
    )

    def __init__(self, database_url: str) -> None:
        if not SQLALCHEMY_AVAILABLE:
            raise RuntimeError("sqlalchemy is required for INVOICE_STORE_BACKEND=postgres")
        if not database_url:
            raise RuntimeError("DATABASE_URL is required for INVOICE_STORE_BACKEND=postgres")
        super().__init__()
        self._engine = create_engine(database_url, future=True, pool_pre_ping=True)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False, future=True)
        if database_url.startswith("sqlite"):
            InvoiceStoreBase.metadata.create_all(self._engine)
        self._load_state()

    def _session(self):
        return self._session_factory()

    def _load_state(self) -> None:
        with self._session() as session:
            row = session.get(_TaskStoreStateRow, self._STORE_KEY)
            if row is None:
                return
            state = pickle.loads(bytes(row.payload))
        if not isinstance(state, dict):
            raise RuntimeError("invalid persisted invoice store state")
        with self._lock:
            for key, value in state.items():
                if isinstance(value, dict) and "__counter__" in value:
                    raw = value["__counter__"]
                    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
                        raise RuntimeError("invalid persisted counter state")
                    setattr(self, key, count(int(raw[0]), int(raw[1])))
                    continue
                setattr(self, key, value)

    def _persist_state(self) -> None:
        with self._lock:
            state: dict[str, object] = {}
            for key, value in self.__dict__.items():
                if key in self._NON_PERSISTED_ATTRS:
                    continue
                if isinstance(value, _COUNT_TYPE):
                    state[key] = _serialize_count(value)
                    continue
                state[key] = value
            payload = pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL)
        now = _now_utc()
        with self._session() as session:
            with session.begin():
                row = session.get(_TaskStoreStateRow, self._STORE_KEY)
                if row is None:
                    session.add(
                        _TaskStoreStateRow(
                            store_key=self._STORE_KEY,
                            payload=payload,
                            updated_at=now,
                        )
                    )
                    return
                row.payload = payload
                row.updated_at = now


def _make_persisting_method(method_name: str) -> Callable:
    base_method = getattr(InMemoryTaskStore, method_name)

    def _wrapped(self: SqlAlchemyTaskStore, *args, **kwargs):
        result = base_method(self, *args, **kwargs)
        self._persist_state()
        return result

    _wrapped.__name__ = method_name
    return _wrapped


for _method_name in SqlAlchemyTaskStore._PERSISTING_METHODS:
    setattr(SqlAlchemyTaskStore, _method_name, _make_persisting_method(_method_name))


def create_task_store(*, backend: str, database_url: str):
    normalized = backend.strip().lower()
    if normalized == "postgres":
        return SqlAlchemyTaskStore(database_url)
    if normalized == "inmemory":
        return InMemoryTaskStore()
    raise RuntimeError(f"unsupported INVOICE_STORE_BACKEND: {backend}")
