"""Real Dataset/plugin/native-driver regression and deterministic process fault lane."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any


def replay_environment(root: Path, artifacts: Path) -> dict[str, str]:
    from onlyalpha_calculation_worker.artifact import manifest
    from onlyalpha_calculation_worker.backtest_dataset import load_dataset_inputs
    from onlyalpha_calculation_worker.backtest_policy import _NoExternalResources
    from onlyalpha_plugin_generic_t0_cash.factory import OnlyGenericT0CashMarketProductFactory

    from onlyalpha.core.ranges import OnlyTimeRange
    from onlyalpha.domain.enums import OnlyMarketType
    from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRawSymbol
    from onlyalpha.domain.instrument import OnlyEquity
    from onlyalpha.domain.market import OnlyBar
    from onlyalpha.domain.value import OnlyCurrency, OnlyMultiplier, OnlyPrice, OnlyQuantity
    from onlyalpha.market.product import (
        OnlyCanonicalMarketProductConfig,
        OnlyMarketProductConfig,
        OnlyMarketProductId,
        OnlyMarketProductPluginId,
        OnlyMarketProductResolutionContext,
        OnlyMarketProductVersion,
    )
    from onlyalpha.research.dataset import OnlyDatasetEconomicBindingStore, OnlyResearchDatasetEconomicBinding
    from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
    from onlyalpha.research.dataset.identity import only_content_fingerprint, only_snapshot_fingerprint
    from onlyalpha.research.dataset.manifest import OnlyResearchDatasetSnapshot
    from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
    from onlyalpha.research.dataset.schema import RESEARCH_BAR_DATASET_SCHEMA_V2

    currency = OnlyCurrency("CNY", 2)
    instrument = OnlyEquity(
        instrument_id=OnlyInstrumentId.parse("600000.XSHG"),
        raw_symbol=OnlyRawSymbol("600000"),
        market_type=OnlyMarketType.CASH,
        quote_currency=currency,
        settlement_currency=currency,
        price_precision=2,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.01"), 2),
        step_size=OnlyQuantity(Decimal("1"), 0),
        contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
    )
    source = next(
        json.loads(line)["record"]
        for line in (root / "test-data/domain/fact-records-v1.jsonl").read_text().splitlines()
        if json.loads(line)["id"] == "bar"
    )
    source["bar_type"]["instrument_id"] = instrument.instrument_id.to_dict()
    original = OnlyBar.from_dict(source)
    bars = []
    for index, price in enumerate((1, 2, 3, 4, 5, 6, 14, 15)):
        row = json.loads(json.dumps(source))
        for key in ("open", "high", "low", "close"):
            row[key]["value"] = f"{price}.00"
        for key in ("bar_start", "bar_end", "ts_event", "ts_init"):
            row[key] = (getattr(original, key) + timedelta(minutes=index)).isoformat().replace("+00:00", "Z")
        bars.append(OnlyBar.from_dict(row))
    definition = OnlyResearchDatasetDefinition(
        (instrument.instrument_id,),
        original.bar_type.semantic,
        OnlyTimeRange(bars[0].bar_start, bars[-1].ts_event + timedelta(seconds=1)),
    )
    content = only_content_fingerprint(tuple(bars))
    construction = "b" * 64
    fingerprint = only_snapshot_fingerprint(
        definition, RESEARCH_BAR_DATASET_SCHEMA_V2, content, len(bars), construction
    )
    snapshot = OnlyResearchDatasetSnapshot(
        definition,
        RESEARCH_BAR_DATASET_SCHEMA_V2,
        content,
        len(bars),
        fingerprint,
        (),
        (),
        datetime(2025, 1, 7, tzinfo=UTC),
        construction,
    )
    datasets = OnlyParquetResearchDatasetSnapshotStore(artifacts / "datasets")
    snapshot = datasets.commit(snapshot, (tuple(bars),))
    product = OnlyGenericT0CashMarketProductFactory().resolve(
        OnlyMarketProductConfig(
            OnlyMarketProductPluginId("onlyalpha-plugin-generic-t0-cash"),
            OnlyMarketProductId("GENERIC_T0_CASH"),
            OnlyMarketProductVersion("1"),
            OnlyCanonicalMarketProductConfig(),
        ),
        OnlyMarketProductResolutionContext(_NoExternalResources(), (instrument,)),
    )
    bindings = OnlyDatasetEconomicBindingStore(artifacts / "bindings")
    binding = bindings.publish_verified(
        OnlyResearchDatasetEconomicBinding(snapshot.snapshot_fingerprint, product.composition_identity.fingerprint, ())
    )
    inputs = load_dataset_inputs(
        datasets, bindings, binding.fingerprint, "c" * 64, "recorded-v1", 0, product.composition_identity.fingerprint
    )
    return {
        "REPLAY_PYTHON": sys.executable,
        "REPLAY_WORKER_ARTIFACT": manifest().implementation_fingerprint,
        "REPLAY_INSTRUMENT": json.dumps(instrument.to_dict(), sort_keys=True, separators=(",", ":")),
        "REPLAY_INPUTS": json.dumps(inputs, sort_keys=True, separators=(",", ":")),
    }


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def check_replay(root: Path, env: dict[str, str], target: str, artifacts: Path) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    build = subprocess.run(
        [
            "cargo",
            "test",
            "-p",
            "onlyalpha-backtest",
            "--test",
            "trading",
            "--no-run",
            "--release",
            "--message-format=json",
            "--frozen",
            "--offline",
            "--target",
            target,
            "-j1",
        ],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    executable = next(
        Path(row["executable"])
        for line in build.stdout.splitlines()
        if (row := json.loads(line)).get("reason") == "compiler-artifact"
        and row.get("executable")
        and row["target"]["name"] == "trading"
    )
    receipts = []
    counter = 0

    def invoke(state: Path, mode: str, cut: str = "") -> None:
        nonlocal counter
        counter += 1
        name = f"{counter:03d}-{mode}-{cut.replace(':', '-')}"
        command = [str(executable), "--exact", "process_writer", "--nocapture", "--test-threads=1"]
        process_env = dict(env, OA_REPLAY_PROCESS_ROOT=str(state), OA_REPLAY_PROCESS_MODE=mode, OA_REPLAY_CUT=cut)
        if not cut:
            result = subprocess.run(command, cwd=root, env=process_env, capture_output=True, timeout=120)
            (artifacts / f"{name}.log").write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError(f"REPLAY_PROCESS_FAILED {name}: {(result.stdout + result.stderr).decode()}")
        else:
            with subprocess.Popen(
                command,
                cwd=root,
                env=process_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            ) as child:
                assert child.stdout is not None
                output = bytearray()
                deadline = time.monotonic() + 120  # Hang guard; ordering is proved by the explicit barrier.
                try:
                    with selectors.DefaultSelector() as selector:
                        selector.register(child.stdout, selectors.EVENT_READ)
                        while b"\nBARRIER\n" not in output:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0 or not selector.select(remaining):
                                raise RuntimeError(f"REPLAY_BARRIER_UNAVAILABLE {name}")
                            chunk = os.read(child.stdout.fileno(), 65536)
                            if not chunk:
                                raise RuntimeError(f"REPLAY_EXITED_BEFORE_BARRIER {name}: {output.decode()}")
                            output.extend(chunk)
                    child.kill()
                    assert child.wait() < 0
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait()
                    (artifacts / f"{name}.log").write_bytes(output)
        receipts.append({"mode": mode, "cut": cut, "log": f"{name}.log"})

    with tempfile.TemporaryDirectory(prefix="replay-", dir=artifacts) as directory:
        work = Path(directory)
        baseline = work / "baseline"
        baseline.mkdir()
        invoke(baseline, "BASELINE")
        expected = json.loads((baseline / "result.json").read_text())
        assert expected["result"]["status"] == "COMPLETED"
        assert expected["result"]["execution_result"]["final_account"]["cash"] == "1007.92"
        assert expected["result"]["execution_result"]["final_account"]["fees"] == "0.08"
        (artifacts / "baseline.json").write_text(_canonical(expected))
        steps = expected["trace"]["steps"]
        selected = []
        for operation in ("ADMIT", "FILL"):
            selected.append(
                next(row["step"] for row in steps if any(i["op"] == operation for i in row["step"]["inputs"]))
            )
        # Closing admission occurs after the opening fill and exercises both paths in one atomic market step.
        close = next(
            row["step"]
            for row in steps
            if any(i["op"] == "ADMIT" and i["payload"]["request"]["side"] == "SELL" for i in row["step"]["inputs"])
        )
        selected.append(close)
        cuts: list[str] = []
        for step in selected:
            index, start = step["index"], step["execution_start"]
            cuts.extend((f"BEFORE_PREPARE:{index}:{start}", f"PREPARED:{index}:{start}"))
            cuts.extend(f"EXECUTION_READY:{index}:{start + n}" for n in range(1, len(step["inputs"]) + 1))
            cuts.append(f"STEP_READY:{index}:{start + len(step['inputs'])}")
        cuts.append("DELIVERY:0:0")
        for index, cut in enumerate(dict.fromkeys(cuts)):
            state = work / f"cut-{index}"
            state.mkdir()
            invoke(state, "RUN", cut)
            invoke(state, "RESUME")
            assert json.loads((state / "result.json").read_text()) == expected, cut
        for mode in ("CANCELLED", "UNKNOWN", "FAILED", "INCOMPLETE"):
            state = work / mode
            state.mkdir()
            invoke(state, mode)
            result = json.loads((state / "result.json").read_text())
            assert result["result"]["outcome"]["status"] == mode
            assert result["result"]["status"] == ("INCOMPLETE" if mode == "UNKNOWN" else mode)
            assert not result["result"]["drained"]
        # Recompute every journal hash after mutations, so codec checks alone cannot pass this proof.
        for mutation in range(10):
            state = work / f"mutation-{mutation}"
            state.mkdir()
            shutil.copyfile(baseline / "runtime.sqlite3", state / "runtime.sqlite3")
            _mutate_journal(state, steps, mutation)
            invoke(state, "REFUSE_RELATION" if mutation < 8 else "REFUSE")
    (artifacts / "faults.json").write_text(_canonical({"schema_version": 1, "cases": receipts}))
    print(f"BACKTEST_REPLAY_REAL_PROCESS_CASES {len(receipts)}", flush=True)


def _mutate_journal(state: Path, steps: list[Any], mutation: int) -> None:
    import sqlite3

    with sqlite3.connect(state / "runtime.sqlite3") as connection:
        if mutation in (8, 9):
            connection.execute("DELETE FROM replay_steps WHERE sequence=?", (1 if mutation == 8 else len(steps),))
        else:
            rows = connection.execute("SELECT sequence,payload FROM replay_steps ORDER BY sequence").fetchall()
            values = [(n, json.loads(payload)) for n, payload in rows]
            value = values[0][1]
            if mutation in (5, 6):
                value = next(
                    changed for _, changed in values if any(item["op"] == "ADMIT" for item in changed["inputs"])
                )
            participant = value["state"]["participants"]
            if mutation == 0:
                participant["binding"] = "e" * 64
            elif mutation == 1:
                value["cause"]["processing"]["input"]["source"] = "e" * 64
            elif mutation == 2:
                value["state"]["clock_ns"] = "1"
            elif mutation == 3:
                participant["preparation"] = steps[-2]["step"]["state"]["participants"]["preparation"]
            elif mutation == 4:
                for field in ("open", "high", "low", "close"):
                    value["cause"]["processing"]["input"]["bar"][field]["value"] = "99.00"
            elif mutation == 5:
                world = participant["world"]
                order = json.loads(world["checkpoint"]["orders"][0])
                order["account_id"]["value"] = "foreign"
                world["checkpoint"]["orders"][0] = _canonical(order)
                world["open_orders"][0] = order
            elif mutation == 6:
                orders = participant["world"]["open_orders"]
                assert len(orders) == 1
                orders.append(json.loads(_canonical(orders[0])))
            else:
                value["cause"]["kind"] = "FOREIGN"
            previous = values[0][1]["previous"]
            for sequence, changed in values:
                changed["previous"] = previous
                previous = _hash(changed)
                connection.execute(
                    "UPDATE replay_steps SET payload=?,digest=? WHERE sequence=?",
                    (_canonical(changed), previous, sequence),
                )
            connection.execute("UPDATE replay_binding SET last_hash=?", (previous,))
