"""One bounded LangGraph turn. Durable occurrences fence every external effect."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

PROMPT = (
    "Clarify one quantitative factor idea. Reply in Chinese as JSON with exactly message and candidate. "
    "candidate is null, or {name,purpose,hypothesis,expression}. expression uses only OHLCV inputs, "
    "integer constants, add/sub/mul/div; history may use lag or mean periods 1..10000. "
    "Never return code or claim approval, Research execution or scientific results. Ask when unclear."
)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def current_identity() -> str:
    """Hash this implementation and its installed dependency artifact closure only."""
    root = Path(__file__).parent
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob("*.py"))}
    pending: list[tuple[str, frozenset[str]]] = [("onlyalpha-agent", frozenset())]
    visited = set()
    artifacts = {}
    while pending:
        name, extras = pending.pop()
        key = (canonicalize_name(name), extras)
        if key in visited:
            continue
        visited.add(key)
        distribution = importlib.metadata.distribution(name)
        if key[0] != "onlyalpha-agent":
            artifacts[key[0]] = {
                "version": distribution.version,
                "files": {
                    str(p): hashlib.sha256(Path(str(distribution.locate_file(p))).read_bytes()).hexdigest()
                    for p in distribution.files or []
                    if "__pycache__" not in p.parts
                    and p.name not in {"RECORD", "INSTALLER", "REQUESTED", "direct_url.json"}
                    and ".." not in p.parts
                    and Path(str(distribution.locate_file(p))).is_file()
                },
            }
        for raw in distribution.requires or []:
            requirement = Requirement(raw)
            if requirement.marker is None or any(
                requirement.marker.evaluate({"extra": extra}) for extra in extras | {""}
            ):
                installed = importlib.metadata.version(requirement.name)
                if installed not in requirement.specifier:
                    raise ValueError("AGENT_DEPENDENCY_ARTIFACT_INCOMPATIBLE")
                pending.append((requirement.name, frozenset(requirement.extras)))
    return digest(
        {
            "contract": "ONLYALPHA_AGENT_WORKFLOW_V1",
            "checkpoint_reader": 1,
            "python": platform.python_version(),
            "interpreter": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
            "platform": [platform.system(), platform.machine(), platform.libc_ver()],
            "files": files,
            "dependencies": artifacts,
        }
    )


class Turn(TypedDict):
    session: str
    command: str
    outcome: dict[str, Any]


def graph(store: Any, command: str, invoke: Any, checkpointer: Any) -> Any:
    def model(state: Turn) -> dict[str, Any]:
        recorded = store.result(command)
        if recorded is not None:
            return {"outcome": recorded}
        plan = store.plan(command)
        # Only the newly accepted occurrence can enter external I/O. Resume never mints this permission.
        result = invoke(plan) if invoke is not None else {"error": "MODEL_OUTCOME_UNKNOWN"}
        store.finish(command, result)
        return {"outcome": result}

    builder = StateGraph(Turn)
    builder.add_node("model", model)
    builder.add_edge(START, "model")
    builder.add_edge("model", END)
    return builder.compile(checkpointer=checkpointer)
