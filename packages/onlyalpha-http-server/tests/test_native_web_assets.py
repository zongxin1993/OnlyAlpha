"""Actual Shipping build bytes through native transport; not business UI acceptance."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.timeout(180)]


def test_shipping_build_and_every_emitted_asset_use_the_native_guarded_http_pipeline(
    integration_http_probe: Path, tmp_path: Path
) -> None:
    root = Path(__file__).resolve().parents[3]
    build = tmp_path / "shipping"
    result = subprocess.run(
        ["npm", "run", "build", "--", "--outDir", str(build), "--emptyOutDir"],
        cwd=root / "packages/onlyalpha-web-console",
        text=True,
        capture_output=True,
        timeout=120,
    )
    log = root / "test-results/rust-product-backend/shipping-web-build.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.stdout + result.stderr)
    assert result.returncode == 0, log.read_text()
    html = (build / "index.html").read_text()
    references = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
    assert references, "Shipping index must reference its actual compiled assets"
    assert 'src="/src/main.tsx"' not in html
    files = {"/": build / "index.html"}
    files.update(
        {"/" + path.relative_to(build).as_posix(): path for path in (build / "assets").rglob("*") if path.is_file()}
    )
    assert set(references) <= set(files)
    result = subprocess.run(
        [str(integration_http_probe)],
        input=json.dumps({"op": "web-assets", "root": str(build), "paths": list(files)}),
        text=True,
        capture_output=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr
    responses = json.loads(result.stdout)["responses"]
    assert [response["path"] for response in responses] == list(files)
    for response in responses:
        data = files[response["path"]].read_bytes()
        assert response["status"] == 200, response
        assert response["size"] == len(data)
        assert response["sha256"] == hashlib.sha256(data).hexdigest()
        assert response["headers"]["cache-control"] == "no-store"
        assert response["headers"]["x-content-type-options"] == "nosniff"
    assert responses[0]["bootstrap_cookie"] is True
    assert all("set-cookie" not in response["headers"] for response in responses[1:])
