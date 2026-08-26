"""Short-lived opaque browser sessions derived from an already verified OIDC identity.

The store never keeps an OIDC bearer token, refresh token, raw claims, or an
Authorization value.  It is deliberately process-local and ephemeral: durable
identity authority remains OIDC and Product API authorization remains server-side.
"""
from __future__ import annotations

from dataclasses import dataclass
import secrets
import time
from typing import Dict, Optional

from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.infrastructure.oidc import VerifiedIdentity


@dataclass(frozen=True)
class OpaqueSession:
    session_id: str
    subject: str
    issuer: str
    audience: str
    expires_at: int

    @property
    def actor(self) -> Actor:
        return Actor(ActorType.USER, self.subject)


class InMemoryOidcSessionStore:
    def __init__(self, *, ttl_seconds: int = 900, clock: Optional[callable] = None) -> None:
        if ttl_seconds < 60 or ttl_seconds > 3600:
            raise ValueError("OIDC_SESSION_TTL_INVALID")
        self._ttl_seconds = ttl_seconds
        self._clock = clock or time.time
        self._sessions: Dict[str, OpaqueSession] = {}

    def issue(self, identity: VerifiedIdentity) -> OpaqueSession:
        self._purge_expired()
        now = int(self._clock())
        session = OpaqueSession(
            session_id=secrets.token_urlsafe(32),
            subject=identity.subject,
            issuer=identity.issuer,
            audience=identity.audience,
            expires_at=now + self._ttl_seconds,
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: Optional[str]) -> Optional[OpaqueSession]:
        if not session_id:
            return None
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.expires_at <= int(self._clock()):
            self._sessions.pop(session_id, None)
            return None
        return session

    def revoke(self, session_id: Optional[str]) -> None:
        if session_id:
            self._sessions.pop(session_id, None)

    def _purge_expired(self) -> None:
        now = int(self._clock())
        for key, session in tuple(self._sessions.items()):
            if session.expires_at <= now:
                self._sessions.pop(key, None)
