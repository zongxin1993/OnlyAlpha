"""Catalog facade preserves owning identities and explicit static re-exports."""

from __future__ import annotations

import ast
import inspect

import pytest

from onlyalpha.application import catalog_context
from onlyalpha.quant_assets import exact_catalog

pytestmark = pytest.mark.contract


def test_catalog_facade_explicitly_reexports_the_same_owning_contracts() -> None:
    names = {name for name in vars(exact_catalog) if name.startswith(("Only", "only_", "EXACT_"))}
    assert set(catalog_context.__all__) == names | {"OnlyExactCatalogContextQueryService"}
    for name in names:
        assert getattr(catalog_context, name) is getattr(exact_catalog, name)

    tree = ast.parse(inspect.getsource(catalog_context))
    explicit_exports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.asname is None or alias.asname == alias.name
    }
    assert names <= explicit_exports
    (exports,) = (
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    )
    assert set(exports) == set(catalog_context.__all__)
    assert not any(alias.name == "*" for node in tree.body if isinstance(node, ast.ImportFrom) for alias in node.names)
