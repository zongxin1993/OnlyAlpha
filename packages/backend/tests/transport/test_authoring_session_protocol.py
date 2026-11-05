"""Technical protocol-loop regression checks with controlled SDK responses."""

import ast
import io
import json
import struct
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2] / "python/algorithms/src/onlyalpha_backend_algorithms"


class Request:
    @staticmethod
    def FromString(data):
        item = json.loads(data)
        operation = item.pop("operation")
        payload = item.pop("payload", {})
        result = types.SimpleNamespace(**item)
        result.WhichOneof = lambda _: operation
        setattr(result, operation, types.SimpleNamespace(request_json=json.dumps(payload)))
        return result


class Response:
    def __init__(self, **fields):
        self.fields = fields
        self.result = types.SimpleNamespace(record_json=b"")
        self.error = types.SimpleNamespace(code="")

    def SerializeToString(self, deterministic):
        return json.dumps(
            {**self.fields, "error": self.error.code, "result": self.result.record_json.decode()}
        ).encode()


class Session:
    initialized = 0
    resolved = 0
    evaluated = 0

    def __init__(self, payload, artifact, core, target):
        if payload.get("fail"):
            raise ValueError("bad init")
        Session.initialized += 1
        self.initialization = {"contract": "ONLYALPHA_AUTHORING_SESSION_V1"}

    def resolve(self, payload):
        if payload.get("contract") != "ONLYALPHA_BOUND_CALCULATION_RESOLVE_V1":
            raise ValueError("bad resolve")
        Session.resolved += 1
        return {"resolved": True}

    def evaluate(self, payload):
        if payload.get("contract") != "ONLYALPHA_BOUND_CALCULATION_EVALUATE_V1":
            raise ValueError("bad evaluate")
        Session.evaluated += 1
        return {"evaluated": True}


def request(sequence, operation, contract="", **fields):
    record = {
        "protocol_version": 1,
        "generation": "generation",
        "sequence": sequence,
        "operation": operation,
        "payload": {"contract": contract, **fields},
    }
    data = json.dumps(record).encode()
    return struct.pack("!I", len(data)) + data


class ProtocolTests(unittest.TestCase):
    def run_worker(self, requests):
        Session.initialized = Session.resolved = Session.evaluated = 0
        restrictions = []
        reader, writer = io.BytesIO(b"".join(requests)), io.BytesIO()
        module = ast.parse((ROOT / "research_worker.py").read_text())
        serve = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "serve")

        def read(stream, count):
            data = stream.read(count)
            if len(data) != count:
                raise EOFError
            return data

        namespace = {
            "Path": Path,
            "Any": object,
            "MAX_FRAME": 8 * 1024 * 1024,
            "CONTRACT": "legacy",
            "INSTANCE_CONTRACT": "instances",
            "verify_installation": lambda *args: None,
            "verify_core": lambda *args: None,
            "verify_distribution": lambda *args: None,
            "read": read,
            "struct": struct,
            "json": json,
            "wire": types.SimpleNamespace(CalculationRequest=Request, CalculationResponse=Response),
            "sys": types.SimpleNamespace(
                stdin=types.SimpleNamespace(buffer=reader), stdout=types.SimpleNamespace(buffer=writer)
            ),
            "restrict": lambda: restrictions.append(True) or "confined",
            "only_canonical_json": json.dumps,
        }
        exec(compile(ast.Module(body=[serve], type_ignores=[]), "<actual staged serve>", "exec"), namespace)
        fake = types.ModuleType("onlyalpha_backend_algorithms.research_session")
        fake.AuthoringSession = Session
        with patch.dict(sys.modules, {fake.__name__: fake}):
            try:
                namespace["serve"](ROOT, "generation", "artifact")
            except EOFError:
                pass
        writer.seek(0)
        responses = []
        while header := writer.read(4):
            responses.append(json.loads(writer.read(struct.unpack("!I", header)[0])))
        return responses, restrictions

    def initial(self):
        return [request(1, "handshake"), request(2, "research_resolve", "ONLYALPHA_AUTHORING_SESSION_V1")]

    def test_one_confinement_for_multiple_same_process_requests(self):
        responses, restrictions = self.run_worker(
            self.initial()
            + [
                request(3, "research_resolve", "ONLYALPHA_BOUND_CALCULATION_RESOLVE_V1"),
                request(4, "research_evaluate", "ONLYALPHA_BOUND_CALCULATION_EVALUATE_V1"),
            ]
        )
        self.assertEqual(len(responses), 4)
        self.assertTrue(all(not row["error"] for row in responses))
        self.assertEqual((Session.initialized, Session.resolved, Session.evaluated), (1, 1, 1))
        self.assertEqual(restrictions, [True])

    def test_second_init_is_rejected_and_failure_cannot_continue(self):
        responses, restrictions = self.run_worker(
            self.initial()
            + [
                request(3, "research_resolve", "ONLYALPHA_AUTHORING_SESSION_V1"),
                request(4, "research_evaluate", "ONLYALPHA_BOUND_CALCULATION_EVALUATE_V1"),
            ]
        )
        self.assertEqual(len(responses), 3)
        self.assertEqual(responses[-1]["error"], "REQUEST_REJECTED")
        self.assertEqual(Session.evaluated, 0)
        self.assertEqual(restrictions, [True])

    def test_failed_init_never_confines_or_continues(self):
        responses, restrictions = self.run_worker(
            [
                request(1, "handshake"),
                request(2, "research_resolve", "ONLYALPHA_AUTHORING_SESSION_V1", fail=True),
                request(3, "research_resolve", "ONLYALPHA_BOUND_CALCULATION_RESOLVE_V1"),
            ]
        )
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[-1]["error"], "REQUEST_REJECTED")
        self.assertEqual(restrictions, [])
        self.assertEqual(Session.resolved, 0)

    def test_session_request_limit_is_1024_after_initialization(self):
        requests = self.initial() + [
            request(i, "research_resolve", "ONLYALPHA_BOUND_CALCULATION_RESOLVE_V1") for i in range(3, 1028)
        ]
        responses, restrictions = self.run_worker(requests)
        self.assertEqual(len(responses), 1026)
        self.assertEqual(Session.resolved, 1024)
        self.assertEqual(restrictions, [True])

    def test_one_shot_failure_closes_and_cannot_enter_session(self):
        responses, restrictions = self.run_worker(
            [
                request(1, "handshake"),
                request(2, "handshake"),
                request(3, "research_resolve", "ONLYALPHA_AUTHORING_SESSION_V1"),
            ]
        )
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[-1]["error"], "REQUEST_REJECTED")
        self.assertEqual(restrictions, [])


if __name__ == "__main__":
    unittest.main()
