import json
import time
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

import jwt
from jwt import algorithms

from hermes_runtime.domain.identity import IdentityAssertionInput, to_authorization_assertion
from hermes_runtime.domain.models import Actor, ActorType


class OidcRejected(ValueError):
    pass


@dataclass(frozen=True)
class OidcConfig:
    issuer: str
    audience: str
    allowed_algorithms: Tuple[str, ...] = ("RS256",)
    jwks_cache_ttl_seconds: int = 300
    production_profile: bool = True
    allow_local_test_issuer: bool = False

    def validate(self) -> None:
        if self.production_profile and self.allow_local_test_issuer:
            raise OidcRejected("OIDC_LOCAL_TEST_ISSUER_FORBIDDEN_IN_PRODUCTION")
        if "none" in {alg.lower() for alg in self.allowed_algorithms}:
            raise OidcRejected("OIDC_ALGORITHM_FORBIDDEN")


@dataclass(frozen=True)
class VerifiedIdentity:
    subject: str
    issuer: str
    audience: str
    actor: Actor
    claims: Mapping[str, object]


class StaticJwksProvider:
    def __init__(self, jwks: Mapping[str, object]) -> None:
        self._jwks = dict(jwks)

    def get_jwks(self) -> Mapping[str, object]:
        return self._jwks


class OidcTokenVerifier:
    def __init__(self, config: OidcConfig, jwks_provider: StaticJwksProvider, clock: Optional[callable] = None) -> None:
        config.validate()
        self._config = config
        self._jwks_provider = jwks_provider
        self._clock = clock or time.time
        self._cached_jwks: Optional[Mapping[str, object]] = None
        self._cache_loaded_at = 0.0

    def verify(self, token: str) -> VerifiedIdentity:
        try:
            header = jwt.get_unverified_header(token)
        except Exception as exc:
            raise OidcRejected("OIDC_TOKEN_MALFORMED") from exc
        alg = header.get("alg")
        kid = header.get("kid")
        if alg not in self._config.allowed_algorithms:
            raise OidcRejected("OIDC_ALGORITHM_FORBIDDEN")
        if not kid:
            raise OidcRejected("OIDC_KID_REQUIRED")
        jwk = self._find_jwk(kid)
        key = algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(self._config.allowed_algorithms),
                issuer=self._config.issuer,
                audience=self._config.audience,
                options={"require": ["exp", "nbf", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise OidcRejected("OIDC_TOKEN_EXPIRED") from exc
        except jwt.ImmatureSignatureError as exc:
            raise OidcRejected("OIDC_TOKEN_NOT_YET_VALID") from exc
        except jwt.InvalidIssuerError as exc:
            raise OidcRejected("OIDC_ISSUER_MISMATCH") from exc
        except jwt.InvalidAudienceError as exc:
            raise OidcRejected("OIDC_AUDIENCE_MISMATCH") from exc
        except Exception as exc:
            raise OidcRejected("OIDC_TOKEN_INVALID") from exc
        subject = str(claims.get("sub", ""))
        if not subject:
            raise OidcRejected("OIDC_SUBJECT_REQUIRED")
        return VerifiedIdentity(
            subject=subject,
            issuer=str(claims["iss"]),
            audience=self._config.audience,
            actor=Actor(ActorType.USER, subject),
            claims=claims,
        )

    def to_gate_assertion(
        self,
        assertion_id: str,
        identity: VerifiedIdentity,
        *,
        project_id: str,
        task_id: Optional[str],
        gate_request_id: str,
        action_scope: str,
    ):
        return to_authorization_assertion(
            assertion_id,
            IdentityAssertionInput(
                issuer=identity.issuer,
                subject=identity.subject,
                role=str(identity.claims.get("role", "approver")),
                project_id=project_id,
                task_id=task_id,
                gate_request_id=gate_request_id,
                action_scope=action_scope,
                valid_from=str(identity.claims.get("nbf", "")),
                valid_until=str(identity.claims.get("exp", "")),
            ),
        )

    def _find_jwk(self, kid: str) -> Mapping[str, object]:
        jwks = self._get_cached_jwks()
        for key in jwks.get("keys", ()):
            if key.get("kid") == kid:
                return key
        self._cached_jwks = None
        jwks = self._get_cached_jwks()
        for key in jwks.get("keys", ()):
            if key.get("kid") == kid:
                return key
        raise OidcRejected("OIDC_UNKNOWN_KEY")

    def _get_cached_jwks(self) -> Mapping[str, object]:
        now = float(self._clock())
        if self._cached_jwks is None or now - self._cache_loaded_at > self._config.jwks_cache_ttl_seconds:
            self._cached_jwks = self._jwks_provider.get_jwks()
            self._cache_loaded_at = now
        return self._cached_jwks
