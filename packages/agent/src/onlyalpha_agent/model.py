"""Bounded external provider adapter, with no tools or automatic retries."""

from __future__ import annotations

import json
import ssl
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


def invoke(profile: dict[str, Any], secret: str, body: dict[str, Any]) -> dict[str, Any]:
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
        if (
            not isinstance(content, dict)
            or set(content) != {"message", "candidate"}
            or not isinstance(content["message"], str)
            or not 0 < len(content["message"]) <= 8000
            or content["candidate"] is not None
            and not isinstance(content["candidate"], dict)
        ):
            raise ValueError
        # Candidate is an unadmitted proposal; Rust retains canonical validation and source derivation in A3.
        return {"response": content, "provider_response": value}
    except HTTPError:
        return {"error": "MODEL_REJECTED"}
    except (OSError, URLError):
        return {"error": "MODEL_OUTCOME_UNKNOWN"}
    except (ValueError, KeyError, IndexError, TypeError, RecursionError):
        return {"error": "MODEL_RESPONSE_INVALID"}
