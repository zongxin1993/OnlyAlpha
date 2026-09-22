"""Deterministic offline OpenAI-compatible Agent Provider fixture.

Serves the exact request sequence certified by the real
``OnlyOpenAICompatibleAgentProviderProbe`` (``GET <base_url>/models`` with
``Authorization: Bearer <token>``) plus a minimal deterministic
chat-completions endpoint shaped for ``OnlyOpenAICompatibleModelAdapterV1``.

Run as: ``python -m tests.runtime_support.openai_compatible_provider_fixture
--host H --port P [--token T] [--model-id M] [--model-version V]``.
"""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DEFAULT_TOKEN = "onlyalpha-dev-agent-provider-secret"
DEFAULT_MODEL_ID = "onlyalpha-dev-model"
DEFAULT_MODEL_VERSION = "1.0.0"

_CHAT_MESSAGE_CONTENT = json.dumps({"message": "onlyalpha-deterministic-fixture-response"}, separators=(",", ":"))


class _Handler(BaseHTTPRequestHandler):
    server_version = "OnlyAlphaOpenAICompatibleProviderFixture/1"
    fixture_token = DEFAULT_TOKEN
    fixture_model_id = DEFAULT_MODEL_ID
    fixture_model_version = DEFAULT_MODEL_VERSION

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler hook
        path = urlparse(self.path).path
        if path == "/health":
            self._json(
                {
                    "status": "ready",
                    "model_id": self.fixture_model_id,
                    "model_version": self.fixture_model_version,
                }
            )
        elif path == "/v1/models":
            if not self._authorized():
                return
            self._json(
                {
                    "object": "list",
                    "data": [
                        {"id": self.fixture_model_id, "object": "model", "owned_by": "onlyalpha-fixture"},
                    ],
                }
            )
        else:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler hook
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        payload = self.rfile.read(length)
        if path != "/v1/chat/completions":
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not self._authorized():
            return
        try:
            request = json.loads(payload)
            if not isinstance(request, dict):
                raise ValueError("request body must be a JSON object")
        except ValueError:
            self._json({"error": "invalid json body"}, HTTPStatus.BAD_REQUEST)
            return
        self._json(
            {
                "id": "onlyalpha-fixture-chat-completion",
                "object": "chat.completion",
                "model": self.fixture_model_id,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": _CHAT_MESSAGE_CONTENT, "refusal": None},
                    },
                ],
            }
        )

    def _authorized(self) -> bool:
        if self.headers.get("Authorization") == f"Bearer {self.fixture_token}":
            return True
        self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        return False

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def only_create_openai_compatible_provider_server(
    host: str,
    port: int,
    *,
    token: str = DEFAULT_TOKEN,
    model_id: str = DEFAULT_MODEL_ID,
    model_version: str = DEFAULT_MODEL_VERSION,
) -> ThreadingHTTPServer:
    class _ConfiguredHandler(_Handler):
        fixture_token = token
        fixture_model_id = model_id
        fixture_model_version = model_version

    return ThreadingHTTPServer((host, port), _ConfiguredHandler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic OpenAI-compatible Agent Provider fixture.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--model-version", default=DEFAULT_MODEL_VERSION)
    args = parser.parse_args()
    server = only_create_openai_compatible_provider_server(
        args.host,
        args.port,
        token=args.token,
        model_id=args.model_id,
        model_version=args.model_version,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
