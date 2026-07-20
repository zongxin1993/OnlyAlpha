from dataclasses import dataclass
from importlib import import_module
from types import ModuleType

from ..errors import OnlyTushareError


@dataclass(frozen=True, slots=True)
class OnlyTushareModules:
    package: ModuleType


def load_tushare() -> OnlyTushareModules:
    try:
        return OnlyTushareModules(import_module("tushare"))
    except ModuleNotFoundError as exc:
        raise OnlyTushareError(
            "TUSHARE_SDK_NOT_INSTALLED", "Tushare SDK is not installed"
        ) from exc
    except Exception as exc:
        raise OnlyTushareError(
            "TUSHARE_IMPORT_FAILED", "Tushare SDK import failed"
        ) from exc
