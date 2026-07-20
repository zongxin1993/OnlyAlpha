"""Load XtQuant only when a factory creates a resource."""

from dataclasses import dataclass
from importlib import import_module
from types import ModuleType

from ..errors import OnlyMiniQmtError


@dataclass(frozen=True, slots=True)
class OnlyXtQuantModules:
    package: ModuleType
    xtdata: ModuleType
    xttrader: ModuleType
    xttype: ModuleType


def load_xtquant() -> OnlyXtQuantModules:
    try:
        package = import_module("xtquant")
        # Some Windows XtQuant builds do not expose submodules from the
        # package root. Explicit imports are stable across those releases.
        return OnlyXtQuantModules(
            package=package,
            xtdata=import_module("xtquant.xtdata"),
            xttrader=import_module("xtquant.xttrader"),
            xttype=import_module("xtquant.xttype"),
        )
    except ModuleNotFoundError as exc:
        if exc.name == "xtquant":
            raise OnlyMiniQmtError("XTQUANT_SDK_NOT_INSTALLED", "xtquant is not installed") from exc
        raise OnlyMiniQmtError("XTQUANT_IMPORT_FAILED", str(exc)) from exc
    except Exception as exc:
        raise OnlyMiniQmtError("XTQUANT_IMPORT_FAILED", str(exc)) from exc
