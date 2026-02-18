from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Protocol

RATE_LIMIT_MAX_ATTEMPTS = 5
RATE_LIMIT_WINDOW = timedelta(minutes=15)
FAILED_LOGIN_RETENTION = timedelta(hours=24)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class PasskeyRecord:
    creator_id: str
    creator_name: str
    passkey_hash: str
    display_prefix: str
    created_at: datetime
    session_version: int


class AuthStateRepository(Protocol):
    def reset(self) -> None: ...

    def generate_passkey(self, creator_id: str, creator_name: str) -> tuple[PasskeyRecord, str]: ...

    def lookup_by_passkey(self, raw_passkey: str) -> PasskeyRecord | None: ...

    def revoke_passkey(self, creator_id: str) -> bool: ...

    def list_passkeys(self) -> list[PasskeyRecord]: ...

    def is_creator_revoked(self, creator_id: str) -> bool: ...

    def current_session_version(self, creator_id: str) -> int: ...

    def check_rate_limit(self, client_ip: str) -> bool: ...

    def record_failed_attempt(self, client_ip: str) -> None: ...


@dataclass
class _CreatorAuthState:
    creator_id: str
    session_version: int
    revoked: bool
    updated_at: datetime


class InMemoryAuthStateRepository:
    def __init__(self) -> None:
        self._lock = Lock()
        self._passkeys: dict[str, PasskeyRecord] = {}
        self._passkey_hash_index: dict[str, str] = {}
        self._auth_state: dict[str, _CreatorAuthState] = {}
        self._login_attempts: dict[str, list[datetime]] = {}

    def reset(self) -> None:
        with self._lock:
            self._passkeys.clear()
            self._passkey_hash_index.clear()
            self._auth_state.clear()
            self._login_attempts.clear()

    def generate_passkey(self, creator_id: str, creator_name: str) -> tuple[PasskeyRecord, str]:
        with self._lock:
            raw_passkey = secrets.token_urlsafe(32)
            passkey_hash = hashlib.sha256(raw_passkey.encode("utf-8")).hexdigest()
            display_prefix = raw_passkey[:6]
            now = _now_utc()

            existing = self._passkeys.get(creator_id)
            if existing is not None:
                self._passkey_hash_index.pop(existing.passkey_hash, None)

            auth_state = self._auth_state.get(creator_id)
            if auth_state is None:
                session_version = 1
                self._auth_state[creator_id] = _CreatorAuthState(
                    creator_id=creator_id,
                    session_version=session_version,
                    revoked=False,
                    updated_at=now,
                )
            else:
                auth_state.session_version += 1
                auth_state.revoked = False
                auth_state.updated_at = now
                session_version = auth_state.session_version

            record = PasskeyRecord(
                creator_id=creator_id,
                creator_name=creator_name,
                passkey_hash=passkey_hash,
                display_prefix=display_prefix,
                created_at=now,
                session_version=session_version,
            )
            self._passkeys[creator_id] = record
            self._passkey_hash_index[passkey_hash] = creator_id
            return record, raw_passkey

    def lookup_by_passkey(self, raw_passkey: str) -> PasskeyRecord | None:
        with self._lock:
            passkey_hash = hashlib.sha256(raw_passkey.encode("utf-8")).hexdigest()
            creator_id = self._passkey_hash_index.get(passkey_hash)
            if creator_id is None:
                return None
            return self._passkeys.get(creator_id)

    def revoke_passkey(self, creator_id: str) -> bool:
        with self._lock:
            record = self._passkeys.pop(creator_id, None)
            if record is None:
                return False
            self._passkey_hash_index.pop(record.passkey_hash, None)
            now = _now_utc()
            auth_state = self._auth_state.get(creator_id)
            if auth_state is None:
                self._auth_state[creator_id] = _CreatorAuthState(
                    creator_id=creator_id,
                    session_version=max(2, record.session_version + 1),
                    revoked=True,
                    updated_at=now,
                )
            else:
                auth_state.session_version += 1
                auth_state.revoked = True
                auth_state.updated_at = now
            return True

    def list_passkeys(self) -> list[PasskeyRecord]:
        with self._lock:
            return sorted(self._passkeys.values(), key=lambda item: item.created_at, reverse=True)

    def is_creator_revoked(self, creator_id: str) -> bool:
        with self._lock:
            state = self._auth_state.get(creator_id)
            return bool(state and state.revoked)

    def current_session_version(self, creator_id: str) -> int:
        with self._lock:
            state = self._auth_state.get(creator_id)
            return state.session_version if state is not None else 1

    def check_rate_limit(self, client_ip: str) -> bool:
        with self._lock:
            now = _now_utc()
            cutoff = now - RATE_LIMIT_WINDOW
            attempts = self._login_attempts.get(client_ip, [])
            recent = [ts for ts in attempts if ts > cutoff]
            self._login_attempts[client_ip] = recent
            return len(recent) < RATE_LIMIT_MAX_ATTEMPTS

    def record_failed_attempt(self, client_ip: str) -> None:
        with self._lock:
            now = _now_utc()
            self._login_attempts.setdefault(client_ip, []).append(now)


SQLALCHEMY_AVAILABLE = True
try:
    from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, create_engine, delete, func, select
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
except ModuleNotFoundError:
    SQLALCHEMY_AVAILABLE = False


if SQLALCHEMY_AVAILABLE:

    class AuthStateBase(DeclarativeBase):
        pass


    class _CreatorPasskeyRow(AuthStateBase):
        __tablename__ = "creator_passkeys"

        creator_id: Mapped[str] = mapped_column(String(128), primary_key=True)
        creator_name: Mapped[str] = mapped_column(String(256), nullable=False)
        passkey_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
        display_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


    class _CreatorAuthStateRow(AuthStateBase):
        __tablename__ = "creator_auth_state"

        creator_id: Mapped[str] = mapped_column(String(128), primary_key=True)
        session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
        revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
        updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


    class _AuthFailedLoginAttemptRow(AuthStateBase):
        __tablename__ = "auth_failed_login_attempts"

        id: Mapped[int] = mapped_column(
            BigInteger().with_variant(Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        )
        client_ip: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
        attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

else:

    class _AuthStateBaseStub:
        metadata = None


    AuthStateBase = _AuthStateBaseStub()


class SqlAlchemyAuthStateRepository:
    def __init__(self, database_url: str) -> None:
        if not SQLALCHEMY_AVAILABLE:
            raise RuntimeError("sqlalchemy is required for AUTH_STORE_BACKEND=postgres")
        if not database_url:
            raise RuntimeError("DATABASE_URL is required for AUTH_STORE_BACKEND=postgres")
        self._engine = create_engine(database_url, future=True, pool_pre_ping=True)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False, future=True)
        # SQLite is used in tests. Production Postgres should rely on migrations.
        if database_url.startswith("sqlite"):
            AuthStateBase.metadata.create_all(self._engine)

    def _session(self):
        return self._session_factory()

    def reset(self) -> None:
        with self._session() as session:
            with session.begin():
                session.execute(delete(_AuthFailedLoginAttemptRow))
                session.execute(delete(_CreatorPasskeyRow))
                session.execute(delete(_CreatorAuthStateRow))

    def generate_passkey(self, creator_id: str, creator_name: str) -> tuple[PasskeyRecord, str]:
        raw_passkey = secrets.token_urlsafe(32)
        passkey_hash = hashlib.sha256(raw_passkey.encode("utf-8")).hexdigest()
        display_prefix = raw_passkey[:6]
        now = _now_utc()

        with self._session() as session:
            with session.begin():
                row = session.get(_CreatorPasskeyRow, creator_id)
                if row is None:
                    row = _CreatorPasskeyRow(
                        creator_id=creator_id,
                        creator_name=creator_name,
                        passkey_hash=passkey_hash,
                        display_prefix=display_prefix,
                        created_at=now,
                    )
                    session.add(row)
                else:
                    row.creator_name = creator_name
                    row.passkey_hash = passkey_hash
                    row.display_prefix = display_prefix
                    row.created_at = now

                state = session.get(_CreatorAuthStateRow, creator_id)
                if state is None:
                    session_version = 1
                    state = _CreatorAuthStateRow(
                        creator_id=creator_id,
                        session_version=session_version,
                        revoked=False,
                        updated_at=now,
                    )
                    session.add(state)
                else:
                    state.session_version += 1
                    state.revoked = False
                    state.updated_at = now
                    session_version = state.session_version

        return (
            PasskeyRecord(
                creator_id=creator_id,
                creator_name=creator_name,
                passkey_hash=passkey_hash,
                display_prefix=display_prefix,
                created_at=now,
                session_version=session_version,
            ),
            raw_passkey,
        )

    def lookup_by_passkey(self, raw_passkey: str) -> PasskeyRecord | None:
        passkey_hash = hashlib.sha256(raw_passkey.encode("utf-8")).hexdigest()
        with self._session() as session:
            row = session.execute(
                select(_CreatorPasskeyRow).where(_CreatorPasskeyRow.passkey_hash == passkey_hash)
            ).scalar_one_or_none()
            if row is None:
                return None
            state = session.get(_CreatorAuthStateRow, row.creator_id)
            session_version = state.session_version if state is not None else 1
            return PasskeyRecord(
                creator_id=row.creator_id,
                creator_name=row.creator_name,
                passkey_hash=row.passkey_hash,
                display_prefix=row.display_prefix,
                created_at=_coerce_utc(row.created_at),
                session_version=session_version,
            )

    def revoke_passkey(self, creator_id: str) -> bool:
        now = _now_utc()
        with self._session() as session:
            with session.begin():
                row = session.get(_CreatorPasskeyRow, creator_id)
                if row is None:
                    return False
                session.delete(row)

                state = session.get(_CreatorAuthStateRow, creator_id)
                if state is None:
                    state = _CreatorAuthStateRow(
                        creator_id=creator_id,
                        session_version=2,
                        revoked=True,
                        updated_at=now,
                    )
                    session.add(state)
                else:
                    state.session_version += 1
                    state.revoked = True
                    state.updated_at = now
        return True

    def list_passkeys(self) -> list[PasskeyRecord]:
        with self._session() as session:
            rows = session.execute(
                select(_CreatorPasskeyRow).order_by(_CreatorPasskeyRow.created_at.desc())
            ).scalars().all()
            result: list[PasskeyRecord] = []
            for row in rows:
                state = session.get(_CreatorAuthStateRow, row.creator_id)
                session_version = state.session_version if state is not None else 1
                result.append(
                    PasskeyRecord(
                        creator_id=row.creator_id,
                        creator_name=row.creator_name,
                        passkey_hash=row.passkey_hash,
                        display_prefix=row.display_prefix,
                        created_at=_coerce_utc(row.created_at),
                        session_version=session_version,
                    )
                )
            return result

    def is_creator_revoked(self, creator_id: str) -> bool:
        with self._session() as session:
            state = session.get(_CreatorAuthStateRow, creator_id)
            return bool(state and state.revoked)

    def current_session_version(self, creator_id: str) -> int:
        with self._session() as session:
            state = session.get(_CreatorAuthStateRow, creator_id)
            return state.session_version if state is not None else 1

    def check_rate_limit(self, client_ip: str) -> bool:
        cutoff = _now_utc() - RATE_LIMIT_WINDOW
        with self._session() as session:
            attempts = session.execute(
                select(func.count())
                .select_from(_AuthFailedLoginAttemptRow)
                .where(
                    _AuthFailedLoginAttemptRow.client_ip == client_ip,
                    _AuthFailedLoginAttemptRow.attempted_at > cutoff,
                )
            ).scalar_one()
            return int(attempts) < RATE_LIMIT_MAX_ATTEMPTS

    def record_failed_attempt(self, client_ip: str) -> None:
        now = _now_utc()
        retention_cutoff = now - FAILED_LOGIN_RETENTION
        with self._session() as session:
            with session.begin():
                session.execute(
                    delete(_AuthFailedLoginAttemptRow).where(
                        _AuthFailedLoginAttemptRow.attempted_at < retention_cutoff
                    )
                )
                session.add(_AuthFailedLoginAttemptRow(client_ip=client_ip, attempted_at=now))
