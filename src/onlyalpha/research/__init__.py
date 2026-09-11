"""Lazy runtime-independent Research public surface."""

from importlib import import_module as _import_module
from typing import TYPE_CHECKING as _TYPE_CHECKING

if _TYPE_CHECKING:
    from onlyalpha.research.agent import *  # noqa: F403
    from onlyalpha.research.artifact import *  # noqa: F403
    from onlyalpha.research.calculation import *  # noqa: F403
    from onlyalpha.research.dataset import *  # noqa: F403
    from onlyalpha.research.definition import *  # noqa: F403
    from onlyalpha.research.evaluation import *  # noqa: F403
    from onlyalpha.research.job import *  # noqa: F403
    from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance as OnlyResearchAuthoringProvenance
    from onlyalpha.research.query import *  # noqa: F403
    from onlyalpha.research.result import *  # noqa: F403
    from onlyalpha.research.run import *  # noqa: F403
    from onlyalpha.research.specification import *  # noqa: F403
    from onlyalpha.research.sweep import *  # noqa: F403
    from onlyalpha.research.workload import OnlyResearchWorkloadPlan as OnlyResearchWorkloadPlan

_PUBLIC_MODULES = (
    "onlyalpha.research.agent",
    "onlyalpha.research.artifact",
    "onlyalpha.research.calculation",
    "onlyalpha.research.dataset",
    "onlyalpha.research.definition",
    "onlyalpha.research.evaluation",
    "onlyalpha.research.job",
    "onlyalpha.research.query",
    "onlyalpha.research.result",
    "onlyalpha.research.run",
    "onlyalpha.research.specification",
    "onlyalpha.research.sweep",
)
_PUBLIC_PREFIXES = (
    "Only",
    "only_",
    "RESEARCH_ARTIFACT_",
    "RESEARCH_SCIENTIFIC_",
    "RESEARCH_QUERY_",
    "DEFAULT_PAGE_",
    "MAX_PAGE_",
)
_exports_loaded = False


def _load_public_exports() -> None:
    global _exports_loaded
    if _exports_loaded:
        return
    for module_name in _PUBLIC_MODULES:
        module = _import_module(module_name)
        exported = getattr(module, "__all__", tuple(name for name in vars(module) if not name.startswith("_")))
        for name in exported:
            globals()[name] = getattr(module, name)
    globals()["OnlyResearchWorkloadPlan"] = _import_module("onlyalpha.research.workload").OnlyResearchWorkloadPlan
    globals()["OnlyResearchAuthoringProvenance"] = _import_module(
        "onlyalpha.research.provenance"
    ).OnlyResearchAuthoringProvenance
    names = [name for name in globals() if name.startswith(_PUBLIC_PREFIXES)]
    list.clear(__all__)
    list.extend(__all__, names)
    _exports_loaded = True


class _LazyPublicNames(list[str]):
    def __iter__(self):  # type: ignore[no-untyped-def]
        _load_public_exports()
        return list.__iter__(self)

    def __len__(self) -> int:
        _load_public_exports()
        return list.__len__(self)

    def __getitem__(self, key):  # type: ignore[no-untyped-def]
        _load_public_exports()
        return list.__getitem__(self, key)

    def __repr__(self) -> str:
        _load_public_exports()
        return list.__repr__(self)

    def __eq__(self, other: object) -> bool:
        _load_public_exports()
        return list.__eq__(self, other)


__all__: list[str] = _LazyPublicNames()


def __getattr__(name: str) -> object:
    _load_public_exports()
    try:
        return globals()[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
