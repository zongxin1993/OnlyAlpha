"""Fuzz the actual admitted native contract inside its caller-owned Host lifecycle."""

from __future__ import annotations

import http.cookiejar
import json
import os
import re
import signal
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

ORIGIN = "http://127.0.0.1:5173"
METHODS = {"get", "post", "put", "patch", "delete"}


def run_contract_fuzz(executable: Path, output: Path, root: Path) -> int:
    # Use the exact source-built ELF already selected by the workstation build.
    exported = subprocess.run(
        [str(executable), "--export-openapi"],
        env={},
        capture_output=True,
        check=True,
        timeout=10,
    ).stdout
    document = json.loads(exported)
    selected = {}
    classification = []
    for path, item in document["paths"].items():
        admitted = {}
        for method, operation in item.items():
            if method not in METHODS:
                admitted[method] = operation
                continue
            responses = set(operation["responses"])
            # Identical projection to routes.rs::operation, not a route allowlist.
            policy = "Deferred" if responses == {"501"} else "Denied" if responses == {"403"} else "Implemented"
            classification.append({"path": path, "method": method.upper(), "policy": policy})
            if policy == "Implemented":
                admitted[method] = operation
        if any(method in admitted for method in METHODS):
            selected[path] = admitted
    if not any(item["policy"] == "Implemented" and item["path"].startswith("/api/v2/") for item in classification):
        raise ValueError("NATIVE_ADMITTED_CONTRACT_EMPTY")
    (output / "openapi-complete.json").write_bytes(exported)
    (output / "contract-operation-policy.json").write_text(json.dumps(classification, indent=2) + "\n")
    # Only operations are selected; every schema/constraint remains untouched.
    document["paths"] = selected
    schema = output / "openapi-admitted.json"
    schema.write_text(json.dumps(document, indent=2) + "\n")
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    request = urllib.request.Request(ORIGIN + "/", headers={"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"})
    with opener.open(request, timeout=10) as response:
        if response.status != 200:
            raise ValueError("NATIVE_NAVIGATION_UNAVAILABLE")
    credential = [cookie.value for cookie in cookies if cookie.name == "onlyalpha_dev_session"]
    if len(credential) != 1:
        raise ValueError("NATIVE_NAVIGATION_SESSION_UNAVAILABLE")
    session_cookie = credential[0]
    if not isinstance(session_cookie, str) or re.fullmatch("[0-9a-f]{64}", session_cookie) is None:
        raise ValueError("NATIVE_NAVIGATION_SESSION_INVALID")
    # Prove the normal cookie reaches an actual supported metadata operation.
    with opener.open(ORIGIN + "/api/v2/integration-types", timeout=10) as response:
        if response.status != 200:
            raise ValueError("NATIVE_AUTHENTICATED_METADATA_UNAVAILABLE")
    policy_results = []
    for operation in classification:
        if operation["policy"] == "Implemented":
            continue
        path = re.sub(r"\{[^/{}]+\}", "retained", operation["path"])
        for candidate in classification:
            pattern = candidate["path"].split("/")
            concrete = path.split("/")
            matches = len(pattern) == len(concrete) and all(
                declared == actual or (declared.startswith("{") and declared.endswith("}") and 0 < len(actual) <= 256)
                for declared, actual in zip(pattern, concrete, strict=True)
            )
            if candidate["method"] == operation["method"] and matches:
                if candidate["policy"] != operation["policy"]:
                    raise ValueError("NATIVE_POLICY_PLACEHOLDER_COLLISION", operation, candidate)
        request = urllib.request.Request(
            ORIGIN + path,
            method=operation["method"],
            data=None if operation["method"] == "GET" else b"{}",
            headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        )
        try:
            response = opener.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            payload = json.load(response)
            expected = 501 if operation["policy"] == "Deferred" else 403
            expected_code = "PRODUCT_CAPABILITY_NOT_IMPLEMENTED"
            if operation["policy"] == "Denied":
                expected_code = (
                    "LOCAL_READ_FORBIDDEN"
                    if path.startswith(("/api/v2/agent/", "/api/v2/trading/", "/api/v2/live/"))
                    else "OWNER_OPERATION_DENIED"
                )
            policy_result = {**operation, "status": response.status, "code": payload["error"]["code"]}
            policy_results.append(policy_result)
            (output / "contract-policy-results.json").write_text(json.dumps(policy_results, indent=2) + "\n")
            # Physical ingress denials precede the method-aware Product dispatcher.
            phase = "QUERY" if expected_code == "LOCAL_READ_FORBIDDEN" or operation["method"] == "GET" else "COMMAND"
            expected_payload = {
                "schema_version": 1,
                "error": {"phase": phase, "code": expected_code, "detail": expected_code},
            }
            if response.status != expected or payload != expected_payload:
                raise ValueError("NATIVE_DECLARED_OPERATION_POLICY_VIOLATION", policy_result)
    command = [
        "uvx",
        "--offline",
        "--from",
        "schemathesis==4.26.1",
        "schemathesis",
        "run",
        str(schema),
        "--url",
        ORIGIN,
        "--checks=not_a_server_error",
        "--max-examples=25",
        "--generation-deterministic",
        "--workers=1",
        "--request-timeout=10",
        "--output-sanitize=true",
    ]
    (output / "schemathesis-command.json").write_text(json.dumps(command, indent=2) + "\n")
    environment = {
        **os.environ,
        "SCHEMATHESIS_HOOKS": "scripts.native_contract_fuzz_hooks",
        "PYTHONPATH": str(root),
        "ONLYALPHA_CONTRACT_FUZZ_COOKIE": session_cookie,
    }
    # The controlled argv is never interpreted by a shell. Separate tool process
    # ownership handles timeout/interruption before the caller drains its Host.
    with (output / "schemathesis.log").open("wb") as log:
        tool = subprocess.Popen(
            command, cwd=output, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            tool_result = tool.wait(timeout=600)
        finally:
            try:
                os.killpg(tool.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                tool.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(tool.pid, signal.SIGKILL)
                tool.wait(timeout=10)
            remaining = []
            for entry in Path("/proc").iterdir():
                if entry.name.isdigit():
                    try:
                        fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                        if int(fields[2]) == tool.pid:
                            remaining.append(int(entry.name))
                    except (FileNotFoundError, ProcessLookupError):
                        continue
            (output / "schemathesis-process-drain.json").write_text(
                json.dumps({"pid": tool.pid, "exit": tool.returncode, "remaining_process_group": remaining}, indent=2)
                + "\n"
            )
            if remaining:
                os.killpg(tool.pid, signal.SIGKILL)
                raise RuntimeError("Schemathesis process group did not drain")
    return tool_result
