"""Dedicated Agent-audience credentials; never backend Human credentials."""

from __future__ import annotations

from dataclasses import dataclass

import jwt

ISSUER = "onlyalpha-agent-access-v1"
AUDIENCE = "onlyalpha-agent"
BROWSER_ISSUER = "onlyalpha-backend-browser-v1"


class Denied(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    subject: str
    token_id: str
    kind: str
    scopes: frozenset[str]

    def require(self, scope: str, *, human: bool = False) -> None:
        if scope not in self.scopes or (human and self.kind != "human"):
            raise Denied("AGENT_OPERATION_DENIED")


def issue_token(
    key: bytes,
    *,
    subject: str,
    audience: str,
    kind: str,
    scopes: list[str],
    token_id: str,
    expires_at: int,
    issuer: str = ISSUER,
) -> str:
    return jwt.encode(
        {
            "v": 1,
            "iss": issuer,
            "aud": audience,
            "sub": subject,
            "kind": kind,
            "scopes": scopes,
            "jti": token_id,
            "exp": expires_at,
        },
        key,
        algorithm="HS256",
    )


def authenticate(key: bytes, authorization: str, *, browser_issuer_key: bytes | None = None) -> Principal:
    try:
        if len(authorization) > 16384 or not authorization.startswith("Bearer "):
            raise ValueError
        issuer = jwt.decode(authorization[7:], options={"verify_signature": False}).get("iss")
        if issuer == BROWSER_ISSUER and browser_issuer_key is not None:
            key = browser_issuer_key
        elif issuer != ISSUER:
            raise ValueError
        claims = jwt.decode(
            authorization[7:],
            key,
            algorithms=["HS256"],
            audience=AUDIENCE,
            issuer=issuer,
            options={"require": ["v", "iss", "aud", "sub", "kind", "scopes", "jti", "exp"]},
        )
        if (
            set(claims) != {"v", "iss", "aud", "sub", "kind", "scopes", "jti", "exp"}
            or type(claims["v"]) is not int
            or claims["v"] != 1
            or type(claims["exp"]) is not int
            or claims["kind"] not in {"human", "service"}
            or not isinstance(claims["sub"], str)
            or not 0 < len(claims["sub"]) <= 200
            or not isinstance(claims["jti"], str)
            or not 0 < len(claims["jti"]) <= 200
            or not isinstance(claims["scopes"], list)
            or any(not isinstance(s, str) or len(s) > 80 for s in claims["scopes"])
        ):
            raise ValueError
        return Principal(claims["sub"], claims["jti"], claims["kind"], frozenset(claims["scopes"]))
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as error:
        raise Denied("AGENT_UNAUTHORIZED") from error
