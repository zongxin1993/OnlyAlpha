"""Production process entrypoint for the request-driven OnlyAlpha Agent node."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from .config import OnlyOpenAICompatibleEndpointConfigV1, OnlyProductApiEndpointConfigV1
from .node_app import create_agent_node_app
from .production import OnlyAgentProductionRuntimeV1
from .provider_integration import (
    OnlyAgentModelProfileV1,
    OnlyAgentProviderRuntimeAuthorityConfigV1,
    OnlyHttpAgentProviderRuntimeAuthorityV1,
)
from .semantic_bundle import load_production_semantic_bundle_v1


def _secret(path: Path) -> str:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("AGENT_SECRET_FILE_INVALID")
    value = path.read_text(encoding="utf-8").strip()
    if not value or "\n" in value or "\r" in value:
        raise ValueError("AGENT_SECRET_FILE_INVALID")
    return value


def _model_profile(path: Path) -> OnlyAgentModelProfileV1:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("AGENT_MODEL_PROFILE_INVALID")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        return OnlyAgentModelProfileV1.from_dict(payload)
    except Exception:
        raise ValueError("AGENT_MODEL_PROFILE_INVALID") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onlyalpha-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve")
    serve.add_argument("--durable-root", type=Path, required=True)
    serve.add_argument("--coordination-root", type=Path, required=True)
    serve.add_argument("--product-api-url")
    serve.add_argument("--product-api-contract", type=Path)
    serve.add_argument("--product-token-file", type=Path)
    serve.add_argument("--model-api-url")
    serve.add_argument("--model-token-file", type=Path)
    serve.add_argument("--integration-runtime-authority-url")
    serve.add_argument("--integration-runtime-authority-token-file", type=Path)
    serve.add_argument("--allow-insecure-runtime-authority-transport", action="store_true")
    serve.add_argument("--model-profile-file", type=Path)
    serve.add_argument(
        "--model-configuration-mode",
        choices=("LEGACY", "INTEGRATION_REVISION"),
        required=True,
    )
    serve.add_argument("--control-token-file", type=Path)
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
    bootstrap_configuration = (
        args.product_api_url,
        args.product_api_contract,
        args.product_token_file,
        args.control_token_file,
    )
    legacy_model_configuration = (args.model_api_url, args.model_token_file)
    integration_model_configuration = (
        args.integration_runtime_authority_url,
        args.integration_runtime_authority_token_file,
        args.model_profile_file,
    )
    configuration = (
        *bootstrap_configuration,
        *legacy_model_configuration,
        *integration_model_configuration,
    )
    if any(value is not None for value in bootstrap_configuration) and not all(
        value is not None for value in bootstrap_configuration
    ):
        raise ValueError("AGENT_CONFIGURATION_INCOMPLETE")
    if not any(value is not None for value in configuration):
        for root in (args.durable_root, args.coordination_root):
            if not root.is_absolute() or root.is_symlink():
                raise ValueError("AGENT_PRODUCTION_ROOT_INVALID")
            root.mkdir(parents=True, exist_ok=True)
        app = create_agent_node_app(
            None,
            control_bearer_token=None,
            readiness=lambda: False,
            configured=False,
        )
        uvicorn.run(app, host=args.host, port=args.port)
        return 0
    if not all(value is not None for value in bootstrap_configuration):
        raise ValueError("AGENT_CONFIGURATION_INCOMPLETE")
    assert all(value is not None for value in bootstrap_configuration)
    product = OnlyProductApiEndpointConfigV1(
        args.product_api_url,
        _secret(args.product_token_file),
        args.product_api_contract,
    )
    if args.model_configuration_mode == "INTEGRATION_REVISION":
        if any(value is not None for value in legacy_model_configuration):
            raise ValueError("CONFIGURATION_MODE_CONFLICT")
        if not all(value is not None for value in integration_model_configuration):
            raise ValueError("AGENT_CONFIGURATION_INCOMPLETE")
        assert all(value is not None for value in integration_model_configuration)
        runtime = OnlyAgentProductionRuntimeV1.compose_from_integration(
            durable_root=args.durable_root,
            coordination_root=args.coordination_root,
            product=product,
            provider_resolver=OnlyHttpAgentProviderRuntimeAuthorityV1(
                OnlyAgentProviderRuntimeAuthorityConfigV1(
                    args.integration_runtime_authority_url,
                    _secret(args.integration_runtime_authority_token_file),
                    allow_insecure_transport=args.allow_insecure_runtime_authority_transport,
                )
            ),
            model_profile=_model_profile(args.model_profile_file),
        )
    else:
        if args.allow_insecure_runtime_authority_transport or any(
            value is not None for value in integration_model_configuration
        ):
            raise ValueError("CONFIGURATION_MODE_CONFLICT")
        if not all(value is not None for value in legacy_model_configuration):
            raise ValueError("AGENT_CONFIGURATION_INCOMPLETE")
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
        readiness=runtime.is_ready,
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover - console-script fallback
    raise SystemExit(main())
