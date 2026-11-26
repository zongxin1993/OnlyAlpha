"""核对独立准备单产生的回测发布正文及其内容寻址引用。"""

import hashlib
import json
from uuid import UUID

_MEMBER_KEYS = ("close_curve", "economic_result", "execution_facts")


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_encode(value)).hexdigest()


def _without(record, field):
    return {key: value for key, value in record.items() if key != field}


class _References:
    def __init__(self, snapshot, preparation):
        assert snapshot["source_ref"] == f"backtest-rules:{preparation}"
        assert type(snapshot["captured_at"]["unix_nanos"]) is int
        self.snapshot = snapshot
        self.identities = {}
        unsigned = _without(snapshot, "fingerprint")
        canonical = {
            **unsigned,
            "captured_at": {**unsigned["captured_at"], "unix_nanos": 0},
            "source_ref": "backtest-rules:00000000-0000-0000-0000-000000000000",
        }
        assert snapshot["fingerprint"] == _hash(unsigned)
        self.canonical_snapshot = {**canonical, "fingerprint": _hash(canonical)}
        self.add(snapshot["fingerprint"], self.canonical_snapshot["fingerprint"])

    def add(self, original, canonical):
        assert self.identities.setdefault(original, canonical) == canonical, original

    def normalize(self, value):
        if isinstance(value, str):
            return self.identities.get(value, value)
        if isinstance(value, list):
            return [self.normalize(item) for item in value]
        if isinstance(value, dict):
            if value == self.snapshot:
                return self.canonical_snapshot
            mapped = {self.identities.get(key, key): self.normalize(item) for key, item in value.items()}
            assert len(mapped) == len(value), "引用归一后出现重复键"
            return mapped
        return value

    def digest(self, record, expected, prefix=""):
        assert expected == prefix + _hash(record), (prefix, expected)
        self.add(expected, prefix + _hash(self.normalize(record)))

    def command(self, command):
        command_id = command["command_id"]
        base, suffix = command_id.rsplit("-", 1)
        assert suffix.isdecimal() and base.startswith("REPLAY-")
        self.add(command_id, f"{self.identities[base]}-{suffix}")


def _position(refs, checkpoint, identity):
    position = checkpoint["positions"][identity]
    for command in position["journal"]:
        refs.command(command)
        state = position["state"]
        refs.digest(command, state["commands"][command["command_id"]])
        if command["op"] == "TRADE":
            payload = command["payload"]
            for field in ("trade", "execution", "venue_trade"):
                key = f"{field}:{payload[field]}"
                refs.add(key, f"{field}:{refs.normalize(payload[field])}")
                refs.digest([payload, str(command["time"])], state["receipts"][key])
    refs.digest(position, identity)


def _account(refs, checkpoint, performance):
    for encoded in checkpoint["journal"]:
        command = encoded
        payload = encoded["payload"]
        if encoded["op"] == "VALUATION":
            identity = payload["position_ref"]
            assert identity == payload["intent"]["position_evidence"]
            command = {**encoded, "payload": {
                "schema_version": 1, "intent": payload["intent"], "position": checkpoint["positions"][identity],
            }}
        refs.command(command)
        refs.digest(command, checkpoint["state"]["receipts"][command["command_id"]])
        aliases = {
            "TRADE": ("trade", "execution", "venue_trade", "fee_instruction"),
            "RESERVE": ("reservation",), "VALUATION": ("valuation",),
        }.get(command["op"], ())
        for field in aliases:
            target = payload["intent"][field] if field == "valuation" else payload[field]
            key = _encode([field, target]).decode()
            refs.add(key, _encode([field, refs.normalize(target)]).decode())
            refs.digest(_without(command, "command_id"), checkpoint["state"]["semantic"][key])
    refs.digest(checkpoint, performance["account_checkpoint"])
    refs.digest(_without(performance, "id"), performance["id"], "AP-")


def _opening_contexts(refs, rows, policy):
    contexts = {}
    for row in rows:
        body = row["body"]
        if row["family"] != "OPEN" or "admission" not in body:
            continue
        opening = body["opening"]
        proof = body["admission"]["market_provenance"]
        assert proof["rules_snapshot"] == refs.snapshot
        cause = proof["cause"]
        refs.digest([body["signal"], opening, policy], cause)
        for prefix in ("NEXT-", "MODEL-ORDER-", "MODEL-TRADE-", "MODEL-VENUE-", "MODEL-MARKET-",
                       "MODEL-FEE-", "MODEL-SET-", "MODEL-VAL-"):
            refs.add(prefix + cause, prefix + refs.normalize(cause))
        if body["status"] == "FILLED":
            assert body["trade"] == "MODEL-TRADE-" + cause
            order = body["order"]
            assert order not in contexts
            contexts[order] = opening["input_identity"], cause
    return contexts


def _execution_input(refs, item, contexts, policy, settings, checkpoint):
    payload = item["payload"]
    op = item["op"]
    if op == "VALUATION":
        _position(refs, checkpoint, payload["position_evidence"])
        identity = payload["valuation"].removeprefix("VALUATION-")
        assert payload["valuation"] == "VALUATION-" + identity
        cause = identity
        binding = {"program": {
            "policy": settings,
            "program": {"scope": {"cluster": item["cluster"]}, "revision": {"strategy_fingerprint": item["revision"]}},
            "opening_profile": {"schema_version": 1, "kind": "OPEN_CLOSE_V1"},
        }}
    else:
        identity, cause = contexts[payload["order"]]
        binding = {"policy": policy}
        if op == "ADMIT":
            request = payload["request"]
            assert request["request_id"]["value"] == "NEXT-" + cause
            refs.digest(request, payload["market"]["request_digest"])
            contract = payload["settlement_fill_contract"]
            refs.digest(contract["model"], contract["model_fingerprint"])
        if op == "FILL":
            assert payload["trade"] == "MODEL-TRADE-" + cause
            for field in ("fees", "settlement", "valuation"):
                proof = payload[field]
                refs.digest(_without(proof, "source_digest"), proof["source_digest"])
    sequence = item["runtime_sequence"]
    refs.digest([identity, cause, sequence, op], item["source_ref"], "CAUSE-")
    refs.digest({"market": identity, "cause": cause, "sequence": sequence, "op": op, "payload": payload, **binding},
                item["input_id"], "REPLAY-")


def _publication(artifacts, preparation):
    assert set(artifacts) == {"causal_evidence", *_MEMBER_KEYS}
    causal = json.loads(artifacts["causal_evidence"])
    body = causal["body"]
    assert body["members"] == [
        {"key": key, "content": hashlib.sha256(artifacts[key]).hexdigest()} for key in _MEMBER_KEYS
    ]
    economics = json.loads(artifacts["economic_result"])
    economic_body = economics["body"]
    facts = json.loads(artifacts["execution_facts"])
    rows = facts["rows"]
    for index, (row, axis) in enumerate(zip(rows, facts["axis"], strict=True), 1):
        assert row["sequence"] == index and axis == [index, row["family"], _hash(row["body"])], index

    binding = body["binding"]
    execution = body["execution"]
    execution_binding = execution["execution_binding"]
    policy = economic_body["preparation"]["policy_binding"]
    assert execution_binding["resolver"] == policy
    snapshot = policy["rules_snapshot"]
    refs = _References(snapshot, preparation)
    assert policy["rules_fingerprint"] == snapshot["fingerprint"]
    refs.digest(snapshot, binding["market_rules"])
    refs.digest(policy, binding["fees"])
    refs.digest(execution_binding, binding["execution_configuration"])
    assert execution["runtime_binding"]["execution"] == binding["execution_configuration"]
    bars = [row["body"]["input_identity"] for row in rows if row["family"] == "BAR"]
    first = bars[binding["market"]["warmup_rows"]]
    quote = economic_body["analytical_baseline"]["entry_fee_quote"]
    refs.digest({"kind": "ANALYTICAL_ESTIMATE", "input": first, "policy": policy}, quote["context"]["cause"])

    contexts = _opening_contexts(refs, rows, policy)
    checkpoint = economic_body["account_checkpoint"]
    economic = economic_body["economic_result"]
    events = [row["body"] for row in rows if row["family"] == "EXECUTION"]
    assert events == [{**fact, "schema_version": 1} for fact in economic["facts"]]
    inputs = []
    for event in events:
        item = event["input"]
        _execution_input(refs, item, contexts, policy, execution_binding["policy_settings"], checkpoint)
        digest = _hash(item)
        refs.digest(item, digest)
        assert event["transaction"] == "ETX-" + digest
        refs.add(event["transaction"], "ETX-" + refs.normalize(digest))
        inputs.append(item)
    refs.digest(inputs, economic["source"]["inputs"])
    _account(refs, checkpoint, economic["runtime_performance"])

    run = binding["scope"].pop("run_id")
    assert str(UUID(run)) == run
    del body["members"], facts["axis"]  # 已按正式字节及有序行逐项验证，可由其余正文唯一重建。
    body["binding"] = refs.normalize(binding)
    execution["runtime_binding"] = refs.normalize(execution["runtime_binding"])
    execution["execution_binding"] = refs.normalize(execution_binding)
    return run, (causal, refs.normalize(economics), refs.normalize(facts))


def assert_equivalent_publications(left_artifacts: dict[str, bytes], right_artifacts: dict[str, bytes],
                                   left_preparation: str, right_preparation: str):
    assert left_preparation != right_preparation
    assert left_artifacts["close_curve"] == right_artifacts["close_curve"], "close_curve 正文字节不一致"
    left_run, left = _publication(left_artifacts, left_preparation)
    right_run, right = _publication(right_artifacts, right_preparation)
    assert left_run != right_run
    for member, original, control in zip(("causal_evidence", "economic_result", "execution_facts"), left, right, strict=True):
        assert _encode(original) == _encode(control), member
