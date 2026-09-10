from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture


def test_agent_context_core_has_no_provider_transport_execution_or_provenance_discovery_dependencies() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "onlyalpha" / "research" / "agent"
    forbidden_import_roots = {
        "anthropic",
        "httpx",
        "openai",
        "psycopg",
        "requests",
        "subprocess",
        "onlyalpha.broker",
        "onlyalpha.execution",
        "onlyalpha.live",
        "onlyalpha_http_server",
    }
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        assert not {
            imported
            for imported in imports
            if any(imported == item or imported.startswith(item + ".") for item in forbidden_import_roots)
        }, path
        source = path.read_text(encoding="utf-8")
        assert "git rev-parse" not in source
        assert "ONLYALPHA_BUILD_SOURCE_REVISION" not in source
        assert "packages/onlyalpha-agent-orchestrator" not in source


def test_agent_session_contract_has_no_mutable_status_or_runtime_occurrence_fields() -> None:
    from onlyalpha.research.agent import OnlyAgentSessionManifestV1

    fields = set(OnlyAgentSessionManifestV1.__dataclass_fields__)
    assert not fields.intersection(
        {
            "status",
            "current_step",
            "progress",
            "current_role",
            "next_action",
            "updated_at",
            "model_call_plan",
            "tool_call_plan",
            "agent_decision",
        }
    )
