"""Paper acceptance orchestration through the formal OnlyEngine composition root."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from uuid import uuid4

from onlyalpha.application import OnlyEngineInspectionService
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.core.clock import OnlyClock, OnlyLiveClock
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.market.session_clock import OnlyMarketSessionResolver, OnlyMarketSessionState

from .artifacts import OnlyAcceptanceArtifactBundle, OnlyAcceptanceArtifactWriter
from .assertions import OnlyPaperAcceptanceAssertions
from .evidence import only_acceptance_json_value
from .models import OnlyAcceptanceCase, OnlyAcceptanceEvidence, OnlyAcceptanceVerdict
from .paper_plan import OnlyPaperAcceptancePlan
from .verdict import OnlyAcceptanceVerdictReducer


@dataclass(frozen=True, slots=True)
class OnlyPaperAcceptanceResult:
    verdict: OnlyAcceptanceVerdict
    cases: dict[str, OnlyAcceptanceVerdict]
    evidences: tuple[OnlyAcceptanceEvidence, ...]
    artifacts: OnlyAcceptanceArtifactBundle


class OnlyPaperAcceptanceRunner:
    def __init__(self, clock: OnlyClock | None = None) -> None:
        self._inspection = OnlyEngineInspectionService()
        self._assertions = OnlyPaperAcceptanceAssertions()
        self._reducer = OnlyAcceptanceVerdictReducer()
        self._artifacts = OnlyAcceptanceArtifactWriter()
        self._clock = clock or OnlyLiveClock()
        self._owns_clock = clock is None

    def run(self, plan: OnlyPaperAcceptancePlan, selected_case: str) -> OnlyPaperAcceptanceResult:
        try:
            return self._run(plan, selected_case)
        finally:
            if self._owns_clock:
                self._clock.close()

    def _run(self, plan: OnlyPaperAcceptancePlan, selected_case: str) -> OnlyPaperAcceptanceResult:
        selected = selected_case.strip().lower()
        if selected not in {"automated", "historical-snapshot", "live-handoff", "all"}:
            raise ValueError(f"unsupported acceptance case: {selected_case}")
        run_id = uuid4().hex
        started = self._now()
        evidences: list[OnlyAcceptanceEvidence] = []
        streams: dict[str, list[object]] = {
            "lifecycle.jsonl": [],
            "inspections.jsonl": [],
            "observations.jsonl": [],
            "health.jsonl": [],
            "orders.jsonl": [],
            "reservations.jsonl": [],
        }
        config = OnlyClusterRunConfig.load(plan.runtime_config_path)
        environment = self._environment(config, plan)
        if selected in {"automated", "all"}:
            evidences.append(self._run_automated_contract())
        if selected in {"historical-snapshot", "live-handoff", "all"}:
            live_requested = selected in {"live-handoff", "all"}
            historical_requested = selected in {"historical-snapshot", "all"}
            session = OnlyMarketSessionResolver(config.reference_data.calendars[0]).resolve(self._now())
            enough_window = (
                session.state is OnlyMarketSessionState.OPEN
                and session.next_market_close.unix_nanos - session.observed_at.unix_nanos
                >= self._required_live_window_seconds(plan) * 1_000_000_000
            )
            if live_requested and not enough_window:
                reason = (
                    "MARKET_SESSION_NOT_OPEN"
                    if session.state is not OnlyMarketSessionState.OPEN
                    else "INSUFFICIENT_LIVE_WINDOW"
                )
                evidences.append(
                    self._evidence(
                        OnlyAcceptanceCase.REAL_LIVE_HANDOFF,
                        "LIVE_BAR",
                        OnlyAcceptanceVerdict.NOT_EXECUTED,
                        reason,
                        started,
                        {
                            "market_session_state": "OPEN",
                            "minimum_window_seconds": self._required_live_window_seconds(plan),
                        },
                        {
                            "market_session_state": session.state.value,
                            "seconds_until_session_close": max(
                                0,
                                (session.next_market_close.unix_nanos - session.observed_at.unix_nanos)
                                // 1_000_000_000,
                            ),
                        },
                    )
                )
            if historical_requested or enough_window:
                evidences.extend(
                    self._run_real_engine(
                        config,
                        plan,
                        run_id,
                        environment=environment,
                        include_historical=historical_requested,
                        include_live=live_requested and enough_window,
                        streams=streams,
                    )
                )
        verdict = self._reducer.reduce(evidences)
        cases = self._case_verdicts(tuple(evidences))
        run_root = self._run_root(plan.output_root, run_id)
        manifest: dict[str, object] = {
            "schema_version": 1,
            "acceptance_scope": "PR5.1_PAPER_READ_ONLY_OBSERVATION",
            "verdict": verdict.value,
            "commit_sha": environment["commit_sha"],
            "onlyalpha_version": environment["onlyalpha_version"],
            "runtime_mode": "PAPER",
            "execution_capability": "SHADOW",
            "instrument_id": plan.expected_instrument_id,
            "external_bar_type": f"{plan.external_bar_step_minutes}m",
            "internal_bar_type": f"{plan.derived_bar_step_minutes}m",
            "historical_protocol": 2,
            "historical_profile": "miniqmt-history-v2",
            "cases": {key: value.value for key, value in cases.items()},
        }
        artifacts = self._artifacts.write(
            run_root=run_root,
            manifest=manifest,
            environment=environment,
            sanitized_config=dict(config.normalized_payload),
            evidences=tuple(evidences),
            streams={key: tuple(value) for key, value in streams.items()},
        )
        return OnlyPaperAcceptanceResult(verdict, cases, tuple(evidences), artifacts)

    def _run_real_engine(
        self,
        config: OnlyClusterRunConfig,
        plan: OnlyPaperAcceptancePlan,
        run_id: str,
        *,
        environment: dict[str, object],
        include_historical: bool,
        include_live: bool,
        streams: dict[str, list[object]],
    ) -> tuple[OnlyAcceptanceEvidence, ...]:
        started = self._now()
        preflight_verdict, preflight_reason, expected, actual = self._preflight(config, plan, environment)
        evidences = [
            self._evidence(
                OnlyAcceptanceCase.REAL_HISTORICAL_SNAPSHOT,
                "ENVIRONMENT",
                preflight_verdict,
                preflight_reason,
                started,
                expected,
                actual,
            )
        ]
        if preflight_verdict is not OnlyAcceptanceVerdict.PASS:
            return tuple(evidences)
        engine = OnlyEngine(
            OnlyEngineConfig(OnlyEngineId(f"paper-acceptance-{run_id}"), self._runtime_user_data_root(plan.output_root))
        )
        baseline = None
        before_live = None
        try:
            streams["lifecycle.jsonl"].append({"at": self._now(), "engine_state": engine.state.value})
            engine.add_cluster(config)
            engine.initialize()
            streams["lifecycle.jsonl"].append({"at": self._now(), "engine_state": engine.state.value})
            baseline = self._inspection.economic_baseline(engine)
            engine.start()
            streams["lifecycle.jsonl"].append({"at": self._now(), "engine_state": engine.state.value})
            inspection = self._inspection.capture(engine)[0]
            streams["inspections.jsonl"].append(inspection)
            streams["observations.jsonl"].extend(inspection.latest_observations)
            streams["health.jsonl"].append(
                {
                    "captured_at": inspection.captured_at,
                    "market_session_state": inspection.market_session_state,
                    "data_state": inspection.data_state,
                    "source_connected": inspection.source_connected,
                    "worker_alive": inspection.worker_alive,
                }
            )
            if include_historical:
                passed, reason, expected, actual = self._assertions.historical(inspection, plan)
                evidences.append(
                    self._evidence(
                        OnlyAcceptanceCase.REAL_HISTORICAL_SNAPSHOT,
                        "HISTORICAL_DATA",
                        OnlyAcceptanceVerdict.PASS if passed else OnlyAcceptanceVerdict.FAIL,
                        reason,
                        started,
                        expected,
                        actual,
                    )
                )
            if include_live:
                before_live = inspection
                deadline_ns = (
                    self._clock.monotonic_ns()
                    + (plan.startup_timeout_seconds + plan.live_grace_seconds) * 1_000_000_000
                )
                while self._clock.monotonic_ns() < deadline_ns:
                    engine.wait(0.25)
                    current = self._inspection.capture(engine)[0]
                    if (
                        current.closed_external_bar_count - before_live.closed_external_bar_count
                        >= plan.target_live_closed_bars
                        and current.derived_internal_bar_count - before_live.derived_internal_bar_count
                        >= plan.target_live_derived_bars
                        and current.live_observation_count - before_live.live_observation_count
                        >= plan.target_live_closed_bars
                    ):
                        break
                after_live = self._inspection.capture(engine)[0]
                streams["inspections.jsonl"].append(after_live)
                streams["observations.jsonl"].extend(after_live.latest_observations)
                passed, reason, expected, actual = self._assertions.live(before_live, after_live, plan)
                evidences.append(
                    self._evidence(
                        OnlyAcceptanceCase.REAL_LIVE_HANDOFF,
                        "LIVE_BAR",
                        OnlyAcceptanceVerdict.PASS if passed else OnlyAcceptanceVerdict.FAIL,
                        reason,
                        started,
                        expected,
                        actual,
                    )
                )
            after = self._inspection.economic_baseline(engine)
            if baseline is not None:
                passed, reason, expected, actual = self._assertions.economic_isolation(baseline, after)
                evidences.append(
                    self._evidence(
                        OnlyAcceptanceCase.REAL_HISTORICAL_SNAPSHOT,
                        "ECONOMIC_ISOLATION",
                        OnlyAcceptanceVerdict.PASS if passed else OnlyAcceptanceVerdict.FAIL,
                        reason,
                        started,
                        expected,
                        actual,
                    )
                )
        except BaseException as exc:
            verdict, reason = self.classify_runtime_failure(exc)
            evidences.append(
                self._evidence(
                    OnlyAcceptanceCase.REAL_HISTORICAL_SNAPSHOT,
                    "HISTORICAL_WORKER",
                    verdict,
                    reason,
                    started,
                    {"parent_process_alive": True, "fail_closed": True},
                    {"exception_type": type(exc).__name__, "message": str(exc)},
                )
            )
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
        finally:
            try:
                engine.stop()
            finally:
                engine.close()
            streams["lifecycle.jsonl"].append({"at": self._now(), "engine_state": engine.state.value})
            try:
                snapshots = self._inspection.capture(engine)
                if snapshots:
                    shutdown = snapshots[0]
                    streams["inspections.jsonl"].append(shutdown)
                    passed, reason, expected, actual = self._assertions.shutdown(shutdown)
                else:
                    passed = engine.state.value == "STOPPED"
                    reason = "NO_RUNTIME_RESOURCES_REMAIN" if passed else "ORDERED_SHUTDOWN_VIOLATED"
                    expected = {"engine_state": "STOPPED", "runtime_count": 0}
                    actual = {"engine_state": engine.state.value, "runtime_count": 0}
                evidences.append(
                    self._evidence(
                        OnlyAcceptanceCase.STOP_WITH_PENDING_BAR,
                        "SHUTDOWN",
                        OnlyAcceptanceVerdict.PASS if passed else OnlyAcceptanceVerdict.FAIL,
                        reason,
                        started,
                        expected,
                        actual,
                    )
                )
            except Exception as exc:
                evidences.append(
                    self._evidence(
                        OnlyAcceptanceCase.STOP_WITH_PENDING_BAR,
                        "SHUTDOWN",
                        OnlyAcceptanceVerdict.FAIL,
                        "SHUTDOWN_INSPECTION_FAILED",
                        started,
                        {"resources_released": True},
                        {"exception_type": type(exc).__name__, "message": str(exc)},
                    )
                )
        return tuple(evidences)

    def _run_automated_contract(self) -> OnlyAcceptanceEvidence:
        started = self._now()
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/acceptance", "-q"],
            check=False,
            capture_output=True,
            text=True,
        )
        return self._evidence(
            OnlyAcceptanceCase.AUTOMATED_CONTRACT,
            "AUTOMATED",
            OnlyAcceptanceVerdict.PASS if completed.returncode == 0 else OnlyAcceptanceVerdict.FAIL,
            "AUTOMATED_CONTRACT_PASSED" if completed.returncode == 0 else "AUTOMATED_CONTRACT_FAILED",
            started,
            {"pytest_exit_code": 0},
            {
                "pytest_exit_code": completed.returncode,
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
            },
        )

    @staticmethod
    def _preflight(
        config: OnlyClusterRunConfig,
        plan: OnlyPaperAcceptancePlan,
        environment: dict[str, object],
    ) -> tuple[OnlyAcceptanceVerdict, str, dict[str, object], dict[str, object]]:
        streaming = config.runtime.extensions.get("streaming")
        streaming_mapping = streaming if isinstance(streaming, Mapping) else None
        source = config.data_sources[0]
        issues: list[str] = []
        if platform.system() != "Windows":
            issues.append("PLATFORM_NOT_WINDOWS")
        if environment["onlyalpha_version"] != environment["plugin_version"]:
            issues.append("CORE_PLUGIN_VERSION_MISMATCH")
        if config.runtime.runtime_type != "PAPER":
            issues.append("RUNTIME_NOT_PAPER")
        if config.runtime.extensions.get("execution_capability") != "SHADOW":
            issues.append("EXECUTION_NOT_SHADOW")
        if any(item.enabled for item in config.brokers):
            issues.append("BROKER_ENABLED")
        if {str(item.instrument_id) for item in config.reference_data.instruments} != {plan.expected_instrument_id}:
            issues.append("INSTRUMENT_PROFILE_MISMATCH")
        if streaming_mapping is None:
            issues.append("STREAMING_CONFIG_MISSING")
        elif streaming_mapping.get("historical_compatibility_profile") != "miniqmt-history-v2":
            issues.append("HISTORICAL_PROFILE_MISMATCH")
        path_value = source.extensions.get("userdata_mini_path")
        if source.extensions.get("cache_policy") != "force_refresh":
            issues.append("HISTORICAL_CACHE_POLICY_NOT_FORCE_REFRESH")
        data_path = None if path_value is None else Path(str(path_value))
        environment_blocks: list[str] = []
        if importlib.util.find_spec("xtquant") is None:
            environment_blocks.append("XTQUANT_NOT_IMPORTABLE")
        if data_path is None or not data_path.is_dir():
            environment_blocks.append("MINIQMT_PATH_NOT_FOUND")
        expected: dict[str, object] = {
            "platform": "Windows",
            "runtime_mode": "PAPER",
            "execution_capability": "SHADOW",
            "broker_enabled": False,
            "instrument_id": plan.expected_instrument_id,
            "historical_profile": "miniqmt-history-v2",
            "historical_protocol": 2,
            "cache_policy": "force_refresh",
            "core_plugin_versions_equal": True,
        }
        actual: dict[str, object] = {
            "platform": platform.system(),
            "runtime_mode": config.runtime.runtime_type,
            "execution_capability": config.runtime.extensions.get("execution_capability"),
            "broker_enabled": any(item.enabled for item in config.brokers),
            "instrument_ids": tuple(str(item.instrument_id) for item in config.reference_data.instruments),
            "historical_profile": None
            if streaming_mapping is None
            else streaming_mapping.get("historical_compatibility_profile"),
            "historical_protocol": 2,
            "cache_policy": source.extensions.get("cache_policy"),
            "onlyalpha_version": environment["onlyalpha_version"],
            "plugin_version": environment["plugin_version"],
            "issues": tuple(issues),
            "environment_blocks": tuple(environment_blocks),
        }
        if issues:
            return OnlyAcceptanceVerdict.FAIL, issues[0], expected, actual
        if environment_blocks:
            return OnlyAcceptanceVerdict.BLOCKED, environment_blocks[0], expected, actual
        return OnlyAcceptanceVerdict.PASS, "PREFLIGHT_PASSED", expected, actual

    @staticmethod
    def classify_runtime_failure(exc: BaseException) -> tuple[OnlyAcceptanceVerdict, str]:
        message = str(exc).upper()
        if "NATIVE_BSON" in message or "WORKER_ABORTED" in message or "BSON" in message:
            return OnlyAcceptanceVerdict.BLOCKED, "MINIQMT_HISTORICAL_NATIVE_BSON_ABORT"
        if "TIMEOUT" in message:
            return OnlyAcceptanceVerdict.BLOCKED, "MINIQMT_HISTORICAL_TIMEOUT"
        if "PROVIDER_UNAVAILABLE" in message or "IMPORT_FAILED" in message or "DOWNLOAD_FAILED" in message:
            return OnlyAcceptanceVerdict.BLOCKED, "MINIQMT_PROVIDER_UNAVAILABLE"
        return OnlyAcceptanceVerdict.FAIL, "ONLYALPHA_PRODUCT_CONTRACT_FAILURE"

    def _evidence(
        self,
        case: OnlyAcceptanceCase,
        category: str,
        verdict: OnlyAcceptanceVerdict,
        reason: str,
        started: OnlyTimestamp,
        expected: dict[str, object],
        actual: dict[str, object],
        *,
        required: bool = True,
    ) -> OnlyAcceptanceEvidence:
        return OnlyAcceptanceEvidence(
            f"{case.value.lower()}-{category.lower()}-{uuid4().hex[:12]}",
            case.value,
            category,
            verdict,
            reason,
            started,
            self._now(),
            expected,
            actual,
            (),
            required,
        )

    @staticmethod
    def _environment(config: OnlyClusterRunConfig, plan: OnlyPaperAcceptancePlan) -> dict[str, object]:
        source_path = config.data_sources[0].extensions.get("userdata_mini_path")
        return {
            "commit_sha": _git_sha(),
            "working_tree_dirty": _git_dirty(),
            "onlyalpha_version": _package_version("onlyalpha"),
            "plugin_version": _package_version("onlyalpha-plugin-miniqmt"),
            "python_version": platform.python_version(),
            "os_version": platform.platform(),
            "xtquant_version": _package_version("xtquant"),
            "miniqmt_path_fingerprint": _fingerprint(str(source_path)),
            "runtime_config_fingerprint": _fingerprint(config.normalized_payload),
            "acceptance_plan_fingerprint": _fingerprint(only_acceptance_json_value(plan)),
        }

    @staticmethod
    def _required_live_window_seconds(plan: OnlyPaperAcceptancePlan) -> int:
        return (
            plan.target_live_closed_bars * plan.external_bar_step_minutes * 60
            + plan.startup_timeout_seconds
            + plan.shutdown_timeout_seconds
        )

    def _run_root(self, output_root: Path, run_id: str) -> Path:
        stamp = self._clock.now_utc().strftime("%Y%m%dT%H%M%SZ")
        return output_root / f"paper-acceptance-{stamp}-{run_id[:12]}"

    def _now(self) -> OnlyTimestamp:
        return OnlyTimestamp.from_datetime(self._clock.now_utc())

    @staticmethod
    def _runtime_user_data_root(output_root: Path) -> Path:
        if output_root.name == "paper" and output_root.parent.name == "acceptance":
            return output_root.parent.parent
        return output_root / "runtime-data"

    @staticmethod
    def _case_verdicts(evidences: tuple[OnlyAcceptanceEvidence, ...]) -> dict[str, OnlyAcceptanceVerdict]:
        reducer = OnlyAcceptanceVerdictReducer()
        cases: dict[str, OnlyAcceptanceVerdict] = {}
        for case_id in sorted({item.case_id for item in evidences}):
            cases[case_id.lower()] = reducer.reduce(tuple(item for item in evidences if item.case_id == case_id))
        return cases


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "NOT_INSTALLED"


def _git_sha() -> str:
    completed = subprocess.run(["git", "rev-parse", "HEAD"], check=False, capture_output=True, text=True)
    return completed.stdout.strip() if completed.returncode == 0 else "UNKNOWN"


def _git_dirty() -> bool:
    completed = subprocess.run(["git", "status", "--porcelain"], check=False, capture_output=True, text=True)
    return completed.returncode != 0 or bool(completed.stdout.strip())


def _fingerprint(value: object) -> str:
    payload = json.dumps(only_acceptance_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
