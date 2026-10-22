"""Supply the normal ephemeral developer identity to pinned Schemathesis calls."""

from __future__ import annotations

import os
import re

import schemathesis


@schemathesis.hook
def before_call(_context, case, _kwargs):  # type: ignore[no-untyped-def]
    credential = os.environ["ONLYALPHA_CONTRACT_FUZZ_COOKIE"]
    if re.fullmatch("[0-9a-f]{64}", credential) is None:
        raise ValueError("NATIVE_NAVIGATION_SESSION_INVALID")
    # Pinned Case.call forwards headers explicitly; only mutate the Case's
    # documented header container, which its own transport serializes.
    case.headers["Cookie"] = "onlyalpha_dev_session=" + credential
    case.headers["Origin"] = "http://127.0.0.1:5173"
