"""Production process entrypoint for the request-driven OnlyAlpha Agent node."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from .config import OnlyOpenAICompatibleEndpointConfigV1, OnlyProductApiEndpointConfigV1
from .node_app import create_agent_node_app
from .production import OnlyAgentProductionRuntimeV1
from .semantic_bundle import load_production_semantic_bundle_v1


def _secret(path: Path) -> str:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("AGENT_SECRET_FILE_INVALID")
    value = path.read_text(encoding="utf-8").strip()
    if not value or "\n" in value or "\r" in value:
        raise ValueError("AGENT_SECRET_FILE_INVALID")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onlyalpha-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve")
    serve.add_argument("--durable-root", type=Path, required=True)
    serve.add_argument("--coordination-root", type=Path, required=True)
    serve.add_argument("--product-api-url", required=True)
    serve.add_argument("--product-api-contract", type=Path, required=True)
    serve.add_argument("--product-token-file", type=Path, required=True)
    serve.add_argument("--model-api-url", required=True)
    serve.add_argument("--model-token-file", type=Path, required=True)
    serve.add_argument("--control-token-file", type=Path, required=True)
    serve.add_argument("--replica-count", type=int, default=1)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8010)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "serve":  # pragma: no cover - argparse closes the grammar
        raise ValueError("AGENT_COMMAND_INVALID")
    if args.replica_count != 1:
        raise ValueError("AGENT_UNSUPPORTED_REPLICA_COUNT")
    product = OnlyProductApiEndpointConfigV1(
        args.product_api_url,
        _secret(args.product_token_file),
        args.product_api_contract,
    )
    semantic_bundle = load_production_semantic_bundle_v1()
    binding = semantic_bundle.invocation_bindings.load_model_invocation_binding_verified("RESEARCH_PLANNER")
    model = OnlyOpenAICompatibleEndpointConfigV1(
        args.model_api_url,
        _secret(args.model_token_file),
        binding.provider_id,
        binding.model_id,
        binding.model_version,
    )
    runtime = OnlyAgentProductionRuntimeV1.compose(
        durable_root=args.durable_root,
        coordination_root=args.coordination_root,
        product=product,
        model=model,
    )
    app = create_agent_node_app(
        runtime.control,
        control_bearer_token=_secret(args.control_token_file),
        readiness=lambda: True,
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover - console-script fallback
    raise SystemExit(main())
