"""Bounded external provider adapter, with no tools or automatic retries."""

from __future__ import annotations

import json
import re
import ssl
from datetime import datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


def endpoint(raw: str) -> str:
    u = urlsplit(raw)
    if (
        not u.hostname
        or u.username is not None
        or u.password is not None
        or u.query
        or u.fragment
        or not (u.scheme == "https" or u.scheme == "http" and u.hostname in {"127.0.0.1", "::1", "localhost"})
    ):
        raise ValueError("AGENT_MODEL_ENDPOINT_INVALID")
    return raw.rstrip("/") + "/chat/completions"


def strict_json(raw: str | bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in items:
            if k in out:
                raise ValueError("duplicate JSON key")
            out[k] = v
        return out

    def invalid(value: str) -> Any:
        raise ValueError(value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def validate_source(value: Any, *, instrument: bool = True) -> None:
    fields = {
        "integration_id",
        "integration_revision_fingerprint",
        "expected_type_id",
        "source_id",
        "environment",
    }
    if instrument:
        fields.add("instrument_id")
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or any(not isinstance(v, str) or not 0 < len(v) <= 512 for v in value.values())
        or re.fullmatch(r"[0-9a-f]{64}", value["integration_revision_fingerprint"]) is None
    ):
        raise ValueError("invalid study source")


def validate_response(content: Any, topic: str = "FACTOR") -> dict[str, Any]:
    field = "study" if topic == "STUDY" else "candidate"
    if (
        topic not in {"FACTOR", "STUDY"}
        or not isinstance(content, dict)
        or set(content) != {"message", field}
        or not isinstance(content["message"], str)
        or not 0 < len(content["message"]) <= 8000
        or content[field] is not None
        and not isinstance(content[field], dict)
    ):
        raise ValueError("invalid model response")
    if topic == "STUDY" and content[field] is not None:
        study = content[field]
        dates = {"start_at", "development_end_at", "end_at", "protected_start_at", "protected_end_at"}
        integers = {"timeframe_minutes", "horizon_bars", "expected_block_length", "replicates", "confidence_bps"}
        if set(study) != dates | integers | {"source", "seed", "rationale"}:
            raise ValueError("invalid study fields")
        validate_source(study["source"])
        for key in dates:
            value = study[key]
            if (
                not isinstance(value, str)
                or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|\+00:00)", value) is None
                or datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() != timedelta(0)
            ):
                raise ValueError("study boundary must be an exact UTC string")
        if any(type(study[key]) is not int or not 0 < study[key] <= 2**32 - 1 for key in integers):
            raise ValueError("study integer invalid")
        if not isinstance(study["seed"], str) or re.fullmatch(r"[0-9a-f]{64}", study["seed"]) is None:
            raise ValueError("study seed invalid")
        if not isinstance(study["rationale"], str) or not 0 < len(study["rationale"].strip()) <= 8000:
            raise ValueError("study rationale invalid")
    return content


def invoke(profile: dict[str, Any], secret: str, body: dict[str, Any], topic: str = "FACTOR") -> dict[str, Any]:
    request = Request(
        endpoint(profile["base_url"]),
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + secret},
    )
    try:
        # Standard TLS verification remains enabled; bypass proxy and redirect credential forwarding.
        from urllib.request import HTTPSHandler

        opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
        with opener.open(request, timeout=60) as response:
            raw = response.read(65537)
        if len(raw) > 65536 or secret.encode() in raw:
            raise ValueError
        value = strict_json(raw)
        content = strict_json(value["choices"][0]["message"]["content"])
        validate_response(content, topic)
        # Candidate is an unadmitted proposal; Rust retains canonical validation and source derivation in A3.
        return {"response": content, "provider_response": value}
    except HTTPError:
        return {"error": "MODEL_REJECTED"}
    except (OSError, URLError):
        return {"error": "MODEL_OUTCOME_UNKNOWN"}
    except (ValueError, KeyError, IndexError, TypeError, RecursionError):
        return {"error": "MODEL_RESPONSE_INVALID"}
