"""Dedicated Agent-audience credentials; never backend Human credentials."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

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


# An assertion transports exact read-only data, not API identity or permissions.
ANALYSIS_ISSUER = "onlyalpha-backend-backtest-analysis-v1"
ANALYSIS_AUDIENCE = "onlyalpha-agent-backtest-analysis"
ANALYSIS_LIMIT = 12288


def _analysis_data(value: Any, run_id: str) -> dict[str, Any]:
    import json
    import re
    from datetime import datetime, timedelta
    from decimal import Decimal, InvalidOperation
    from uuid import UUID

    def exact(record: Any, fields: str) -> None:
        if not isinstance(record, dict) or set(record) != set(fields.split()):
            raise ValueError

    def text(item: Any, maximum: int = 512) -> None:
        if not isinstance(item, str) or not 0 < len(item) <= maximum or "\0" in item:
            raise ValueError

    def number(item: Any) -> None:
        text(item, 200)
        if not Decimal(item).is_finite():
            raise ValueError

    def count(item: Any) -> None:
        if type(item) is not int or not 0 <= item <= 8192:
            raise ValueError

    def utc(item: Any) -> datetime:
        text(item, 64)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|\+00:00)", item) is None:
            raise ValueError
        parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
        if parsed.utcoffset() != timedelta(0):
            raise ValueError
        return parsed

    try:
        exact(
            value,
            "schema_version profile run_id specification_fingerprint strategy_fingerprint evidence_fingerprint result_fingerprint determinism_fingerprint state sample metrics baseline trades trade_count trades_truncated limitations",
        )
        if (
            type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["profile"] != "ONLYALPHA_BACKTEST_ANALYSIS_DATA_V1"
            or value["state"] != "COMPLETED"
        ):
            raise ValueError
        if value["run_id"] != run_id or str(UUID(run_id, version=4)) != run_id:
            raise ValueError
        for key in (
            "specification_fingerprint",
            "strategy_fingerprint",
            "evidence_fingerprint",
            "result_fingerprint",
            "determinism_fingerprint",
        ):
            if not isinstance(value[key], str) or re.fullmatch(r"[0-9a-f]{64}", value[key]) is None:
                raise ValueError
        sample = value["sample"]
        exact(sample, "instrument start_at end_at quantity rule_observed_at")
        text(sample["instrument"])
        if utc(sample["start_at"]) >= utc(sample["end_at"]):
            raise ValueError
        utc(sample["rule_observed_at"])
        number(sample["quantity"])
        metrics = value["metrics"]
        exact(
            metrics,
            "initial_equity final_equity return_since_start net_pnl realized_pnl unrealized_pnl fees maximum_drawdown fill_count roundtrip_count",
        )
        for key in ("initial_equity", "final_equity", "net_pnl", "realized_pnl", "unrealized_pnl", "fees"):
            number(metrics[key])
        for key in ("return_since_start", "maximum_drawdown"):
            if metrics[key] is not None:
                number(metrics[key])
        count(metrics["fill_count"])
        count(metrics["roundtrip_count"])
        if value["baseline"] is not None:
            exact(value["baseline"], "final_equity net_pnl return_since_start")
            for item in value["baseline"].values():
                number(item)
        trades = value["trades"]
        if not isinstance(trades, list) or len(trades) > 8:
            raise ValueError
        count(value["trade_count"])
        if (
            value["trade_count"] != metrics["fill_count"]
            or value["trade_count"] < len(trades)
            or type(value["trades_truncated"]) is not bool
            or value["trades_truncated"] != (value["trade_count"] > len(trades))
        ):
            raise ValueError
        for ordinal, trade in enumerate(trades, 1):
            exact(trade, "ordinal time_ns side quantity price fee signal_time_ns signal order_id trade_id")
            if type(trade["ordinal"]) is not int or trade["ordinal"] != ordinal or trade["side"] not in {"BUY", "SELL"}:
                raise ValueError
            for key in ("time_ns", "signal_time_ns"):
                if not isinstance(trade[key], str) or re.fullmatch(r"[0-9]{1,20}", trade[key]) is None:
                    raise ValueError
            for key in ("quantity", "price", "fee"):
                number(trade[key])
            for key in ("signal", "order_id", "trade_id"):
                text(trade[key])
        if not isinstance(value["limitations"], list) or not 1 <= len(value["limitations"]) <= 16:
            raise ValueError
        for item in value["limitations"]:
            text(item, 1000)
        if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > 8192:
            raise ValueError
        return cast(dict[str, Any], value)
    except (ValueError, TypeError, KeyError, InvalidOperation, OverflowError) as error:
        raise Denied("AGENT_BACKTEST_CONTEXT_DENIED") from error


def _read_backtest_analysis(
    key: bytes | None, assertion: str, owner: str, run_id: str, accepted_at: int | None
) -> dict[str, Any]:
    try:
        if (
            key is None
            or len(key) != 32
            or not isinstance(assertion, str)
            or len(assertion.encode("ascii")) > ANALYSIS_LIMIT
        ):
            raise ValueError
        header = jwt.get_unverified_header(assertion)
        if header != {"alg": "HS256", "typ": "JWT"}:
            raise ValueError
        claims = jwt.decode(
            assertion,
            key,
            algorithms=["HS256"],
            issuer=ANALYSIS_ISSUER,
            audience=ANALYSIS_AUDIENCE,
            options={
                "require": ["v", "iss", "aud", "sub", "kind", "jti", "iat", "exp", "data"],
                "verify_exp": accepted_at is None,
                "verify_iat": accepted_at is None,
            },
        )
        if (
            set(claims) != {"v", "iss", "aud", "sub", "kind", "jti", "iat", "exp", "data"}
            or type(claims["v"]) is not int
            or claims["v"] != 1
        ):
            raise ValueError
        if (
            claims["iss"] != ANALYSIS_ISSUER
            or claims["aud"] != ANALYSIS_AUDIENCE
            or claims["sub"] != owner
            or claims["kind"] != "BACKTEST_ANALYSIS_DATA"
        ):
            raise ValueError
        if (
            not isinstance(claims["jti"], str)
            or not 0 < len(claims["jti"]) <= 200
            or not isinstance(owner, str)
            or not 0 < len(owner) <= 200
        ):
            raise ValueError
        if (
            type(claims["iat"]) is not int
            or type(claims["exp"]) is not int
            or not 0 < claims["exp"] - claims["iat"] <= 300
        ):
            raise ValueError
        if accepted_at is not None and (
            type(accepted_at) is not int or not claims["iat"] <= accepted_at < claims["exp"]
        ):
            raise ValueError
        return _analysis_data(claims["data"], run_id)
    except (jwt.PyJWTError, ValueError, TypeError, KeyError, UnicodeError) as error:
        raise Denied("AGENT_BACKTEST_CONTEXT_DENIED") from error


def verify_backtest_analysis(key: bytes | None, assertion: str, *, owner: str, run_id: str) -> dict[str, Any]:
    """Fresh message admission. Standard PyJWT verifies signature and current expiry."""
    return _read_backtest_analysis(key, assertion, owner, run_id, None)


def _recorded_backtest_analysis(
    key: bytes | None, assertion: str, owner: str, run_id: str, accepted_at: int
) -> dict[str, Any]:
    """Historical reader only, after the original keyed Command occurrence check.

    Original acceptance must lie within the signed lifetime. This does not admit
    another message or grant another model call when current time has advanced.
    """
    return _read_backtest_analysis(key, assertion, owner, run_id, accepted_at)
