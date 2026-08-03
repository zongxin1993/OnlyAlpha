"""Atomic, redacted acceptance artifact writing; COMPLETE is always last."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .evidence import only_acceptance_json_value, only_evidence_to_dict
from .models import OnlyAcceptanceEvidence, OnlyAcceptanceVerdict
from .redaction import only_redact_acceptance_value


@dataclass(frozen=True, slots=True)
class OnlyAcceptanceArtifactBundle:
    run_root: Path
    manifest_path: Path
    assertions_path: Path
    report_path: Path
    complete_path: Path


class OnlyAcceptanceArtifactWriter:
    def write(
        self,
        *,
        run_root: Path,
        manifest: dict[str, object],
        environment: dict[str, object],
        sanitized_config: dict[str, object],
        evidences: tuple[OnlyAcceptanceEvidence, ...],
        streams: dict[str, tuple[object, ...]] | None = None,
    ) -> OnlyAcceptanceArtifactBundle:
        run_root.mkdir(parents=True, exist_ok=False)
        (run_root / "worker").mkdir()
        assertions = [only_evidence_to_dict(item) for item in evidences]
        self._json(run_root / "manifest.json", only_redact_acceptance_value(manifest))
        self._json(run_root / "environment.json", only_redact_acceptance_value(environment))
        self._json(run_root / "sanitized_config.json", only_redact_acceptance_value(sanitized_config))
        for name in (
            "lifecycle.jsonl",
            "inspections.jsonl",
            "observations.jsonl",
            "health.jsonl",
            "orders.jsonl",
            "reservations.jsonl",
        ):
            self._jsonl(run_root / name, () if streams is None else streams.get(name, ()))
        self._json(run_root / "assertions.json", assertions)
        verdict = OnlyAcceptanceVerdict(str(manifest["verdict"]))
        self._bytes(run_root / "report.md", self._report(verdict, evidences, manifest).encode("utf-8"))
        complete = run_root / "COMPLETE"
        self._bytes(complete, b"")
        return OnlyAcceptanceArtifactBundle(
            run_root,
            run_root / "manifest.json",
            run_root / "assertions.json",
            run_root / "report.md",
            complete,
        )

    @staticmethod
    def _report(
        verdict: OnlyAcceptanceVerdict,
        evidences: tuple[OnlyAcceptanceEvidence, ...],
        manifest: dict[str, object],
    ) -> str:
        automated = [item for item in evidences if item.case_id == "AUTOMATED_CONTRACT"]
        real = [item for item in evidences if item.case_id.startswith("REAL_")]
        not_executed = [item for item in evidences if item.verdict is OnlyAcceptanceVerdict.NOT_EXECUTED]

        def rows(items: list[OnlyAcceptanceEvidence]) -> str:
            return (
                "\n".join(f"- {item.category}: {item.verdict.value} ({item.reason_code})" for item in items) or "- None"
            )

        return (
            "# Paper Real Product Acceptance\n\n"
            f"Overall: {verdict.value}\n\n"
            "## AUTOMATED RESULTS\n\n"
            f"{rows(automated)}\n\n"
            "## REAL ENVIRONMENT RESULTS\n\n"
            f"{rows(real)}\n\n"
            "## NOT EXECUTED RESULTS\n\n"
            f"{rows(not_executed)}\n\n"
            "## KNOWN EXTERNAL LIMITATIONS\n\n"
            "- Streaming reconnect, gap recovery, streaming recovery, broad MiniQMT compatibility, and Live Runtime remain outside this scope.\n\n"
            f"Production Paper Runtime: PARTIAL\n\nManifest schema: {manifest.get('schema_version', 1)}\n"
        )

    def _json(self, path: Path, value: object) -> None:
        encoded = (
            json.dumps(only_acceptance_json_value(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode()
        self._bytes(path, encoded)

    def _jsonl(self, path: Path, values: tuple[object, ...]) -> None:
        encoded = "".join(
            json.dumps(
                only_acceptance_json_value(only_redact_acceptance_value(item)), ensure_ascii=False, sort_keys=True
            )
            + "\n"
            for item in values
        ).encode("utf-8")
        self._bytes(path, encoded)

    @staticmethod
    def _bytes(path: Path, value: bytes) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        with temporary.open("wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
