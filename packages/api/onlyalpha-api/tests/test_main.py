from __future__ import annotations

import onlyalpha_api.main as server
import pytest


def test_servers_require_explicit_roots() -> None:
    with pytest.raises(SystemExit) as full:
        server.main([])
    assert full.value.code == 2
