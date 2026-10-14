"""Verify explicit installed Python resource closures without discovery or code loading."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
import tomllib
from importlib import metadata
from importlib.util import resolve_name
from inspect import CO_NEWLOCALS
from pathlib import Path
from types import CodeType, FunctionType
from urllib.parse import unquote, urlsplit

from onlyalpha.calculation.implementation import OnlyCalculationImplementationManifest


def only_require_installed_distribution_module(
    distribution_name: str, distribution_version: str, module_name: str
) -> None:
    """Require wheel ownership or the explicitly installed editable source project."""
    distribution = metadata.distribution(distribution_name)
    module = sys.modules.get(module_name)
    if distribution.version != distribution_version or module is None or module.__file__ is None:
        raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
    module_path = Path(module.__file__).resolve()
    for resource in distribution.files or ():
        if Path(str(distribution.locate_file(resource))).resolve() == module_path:
            if resource.hash is None or resource.hash.mode != "sha256":
                raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
            import base64

            digest = base64.urlsafe_b64encode(hashlib.sha256(module_path.read_bytes()).digest()).decode().rstrip("=")
            if digest != resource.hash.value:
                raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
            return
    direct = distribution.read_text("direct_url.json")
    if direct is None:
        raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
    origin = json.loads(direct)
    url = urlsplit(origin["url"])
    if url.scheme != "file" or url.netloc or origin.get("dir_info") != {"editable": True}:
        raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
    project = Path(unquote(url.path)).resolve()
    package_root = project / "src" / module_name.split(".")[0]
    if package_root not in module_path.parents:
        raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
    identity = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if identity["name"] != distribution_name or identity["version"] != distribution_version:
        raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")


def only_require_manifest_resources(
    manifest: OnlyCalculationImplementationManifest, distribution_name: str, distribution_version: str
) -> None:
    module_name = manifest.entrypoint_identity.split(":")[0]
    module = sys.modules.get(module_name)
    if module is None or module.__file__ is None:
        raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
    root = Path(module.__file__).resolve().parent
    package = module_name.rsplit(".", 1)[0]
    for resource in manifest.resources:
        path = root / resource.relative_path
        if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:
            raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
        if hashlib.sha256(path.read_bytes()).hexdigest() != resource.byte_sha256:
            raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
        resource_module = package + "." + resource.relative_path[:-3].replace("/", ".")
        only_require_installed_distribution_module(distribution_name, distribution_version, resource_module)


def only_require_installed_implementation(manifest: OnlyCalculationImplementationManifest, provider: object) -> None:
    module_name, qualname = manifest.entrypoint_identity.split(":")
    module = sys.modules.get(module_name)
    if module is None or module.__file__ is None:
        raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
    entry: object = module
    for part in qualname.split("."):
        entry = getattr(entry, part, None)
    if entry is not type(provider):
        raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
    root = Path(module.__file__).resolve().parent
    package = module_name.rsplit(".", 1)[0]
    if not any(resource.relative_path == Path(module.__file__).name for resource in manifest.resources):
        raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
    for resource in manifest.resources:
        path = root / resource.relative_path
        if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:
            raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != resource.byte_sha256:
            raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
        resource_module = sys.modules.get(f"{package}.{Path(resource.relative_path).stem}")
        if (
            resource_module is None
            or resource_module.__file__ is None
            or Path(resource_module.__file__).resolve() != path
        ):
            raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
        only_require_loaded_python_code(resource_module.__name__, content, path)


def only_require_loaded_python_code(module_name: str, content: bytes, path: Path) -> None:
    """Check module functions and explicitly authored methods against compiled source, never exec it.

    This catches stale imports, reload and method/helper replacement. It is an installation
    coherence check, not a sandbox against arbitrary code already controlling the process.
    Generated dataclass methods are intentionally not source-authored functions.
    """
    module = sys.modules.get(module_name)
    if module is None:
        raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
    code = compile(content, str(path), "exec", dont_inherit=True, optimize=sys.flags.optimize)
    tree = ast.parse(content)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module != "__future__":
            origin_name = (
                resolve_name("." * node.level + (node.module or ""), module.__package__ or "")
                if node.level
                else node.module
            )
            origin = sys.modules.get(origin_name or "")
            for alias in node.names:
                if alias.name != "*" and getattr(module, alias.asname or alias.name, None) is not getattr(
                    origin, alias.name, None
                ):
                    raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_name = alias.name if alias.asname else alias.name.split(".")[0]
                if getattr(module, alias.asname or imported_name, None) is not sys.modules.get(imported_name):
                    raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
    authored: dict[str, CodeType] = {}
    definitions_by_location = {
        (node.name, min([node.lineno, *(item.lineno for item in node.decorator_list)])): node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    def collect(parent: CodeType) -> None:
        for child in parent.co_consts:
            if isinstance(child, CodeType):
                authored[child.co_qualname] = child
                collect(child)

    collect(code)
    for name, expected in authored.items():
        if "<" in name:
            continue
        value: object = module
        for part in name.split("."):
            value = getattr(value, part, None)
        if not expected.co_flags & CO_NEWLOCALS:
            if not isinstance(value, type) or value.__module__ != module_name:
                raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
            continue
        if isinstance(value, property):
            value = value.fget
        if hasattr(value, "__func__"):
            value = value.__func__
        if not isinstance(value, FunctionType) or value.__code__ != expected or value.__globals__ is not vars(module):
            raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
        definition = definitions_by_location.get((expected.co_name, expected.co_firstlineno))
        if definition is None:
            raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
        arguments = definition.args
        defaults = value.__defaults__ or ()
        keyword_defaults = value.__kwdefaults__ or {}
        expected_keywords = {
            arg.arg
            for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
            if default is not None
        }
        if len(defaults) != len(arguments.defaults) or set(keyword_defaults) != expected_keywords:
            raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
        for expression, actual in [
            *zip(arguments.defaults, defaults, strict=True),
            *(
                (default, keyword_defaults[arg.arg])
                for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
                if default is not None
            ),
        ]:
            try:
                declared = ast.literal_eval(expression)
            except (ValueError, TypeError):
                # Non-literal declarations are independently bound by registration/identity checks.
                continue
            if type(actual) is not type(declared) or actual != declared:
                raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
