"""Loaded implementation provenance, distinct from formal Generation admission."""

from __future__ import annotations

import _decimal
import hashlib
import sys
import sysconfig
from functools import cache
from pathlib import Path

import onlyalpha_gateway_protocol
import onlyalpha_plugin_indicators
from google._upb import _message

import onlyalpha
from onlyalpha.calculation.decimal_execution import only_decimal_execution_semantic_dependency
from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationTypeReference,
)
from onlyalpha.calculation.implementation import (
    OnlyCalculationImplementationManifest,
    OnlyCalculationImplementationResource,
    OnlyCalculationSemanticDependency,
    only_distribution_semantic_dependency,
    only_python_stdlib_semantic_dependency,
)


@cache
def manifest() -> OnlyCalculationImplementationManifest:
    resources = []
    for label, root in (
        ("core", Path(onlyalpha.__file__).parent),
        ("plugin", Path(onlyalpha_plugin_indicators.__file__).parent),
        ("protocol", Path(onlyalpha_gateway_protocol.__file__).parent),
        ("worker", Path(__file__).parent),
    ):
        paths = sorted(root.rglob("*.py"))
        if label == "protocol":
            paths += sorted(root.rglob("*.pb"))
        for path in paths:
            resources.append(
                OnlyCalculationImplementationResource(
                    f"{label}/{path.relative_to(root).as_posix()}", hashlib.sha256(path.read_bytes()).hexdigest()
                )
            )
    for label, path in (
        ("decimal-native", Path(_decimal.__file__)),
        ("protobuf-native", Path(_message.__file__)),
        ("python-executable", Path(sys.executable)),
        ("python-library", Path(sysconfig.get_config_var("LIBDIR")) / sysconfig.get_config_var("LDLIBRARY")),
    ):
        resources.append(
            OnlyCalculationImplementationResource(f"runtime/{label}", hashlib.sha256(path.read_bytes()).hexdigest())
        )
    return OnlyCalculationImplementationManifest(
        OnlyCalculationTypeReference(OnlyCalculationKind.INDICATOR, "onlyalpha.calculation.worker", "1"),
        OnlyCalculationBackendKind.TRADING,
        "onlyalpha_calculation_worker.worker:serve",
        tuple(resources),
        (
            OnlyCalculationSemanticDependency("cpython.worker-runtime", sys.version),
            only_decimal_execution_semantic_dependency(),
            only_python_stdlib_semantic_dependency("decimal"),
            only_distribution_semantic_dependency("protobuf"),
            only_distribution_semantic_dependency("pyarrow"),
        ),
    )
