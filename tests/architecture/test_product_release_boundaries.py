"""Product releases own one build graph without library-to-product dependencies."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_backend_has_one_version_and_no_internal_product_package_dependency() -> None:
    workspace = tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]
    products = [path for path in workspace["members"] if path.startswith("packages/")]
    assert products == ["packages/backend"]
    backend = tomllib.loads((ROOT / products[0] / "Cargo.toml").read_text())
    assert isinstance(backend["package"]["version"], str)
    assert backend["package"]["name"] == "onlyalpha-backend"
    assert not {"onlyalpha-http-server", "onlyalpha-product-runtime"}.intersection(backend["dependencies"])
    assert {item["name"] for item in backend["bin"]} == {"onlyalpha-backend"}


def test_reusable_libraries_and_plugins_cannot_depend_on_backend() -> None:
    for directory in (ROOT / "crates", ROOT / "plugs"):
        for path in directory.rglob("Cargo.toml"):
            manifest = tomllib.loads(path.read_text())
            for section in (manifest, *manifest.get("target", {}).values()):
                for kind in ("dependencies", "dev-dependencies", "build-dependencies"):
                    for alias, value in section.get(kind, {}).items():
                        name = value.get("package", alias) if isinstance(value, dict) else alias
                        assert name != "onlyalpha-backend", path
