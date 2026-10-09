"""Pure sealed Revision identities shared by owning and portable readers."""

from __future__ import annotations

from datetime import datetime

from onlyalpha.canonical import only_canonical_fingerprint

from .models import OnlyCoverageManifest, OnlyCoverageStatus, OnlyMarketDataRevision, OnlyMarketDataSeal

_REQUIRED_SEAL_CHECKS = (
    "SEGMENT_HASH_VERIFIED",
    "SCHEMA_COMPATIBLE",
    "CANONICAL_IDENTITY_UNIQUE",
    "REQUESTED_SCOPE_VERIFIED",
    "COVERAGE_COMPLETE",
    "NO_UNRESOLVED_CORRUPTION",
)


class OnlyMarketDataSealError(RuntimeError):
    pass


def only_native_bar_coverage_proof(fact_count: int, grid_count: int, semantic_valid: bool) -> tuple[str, ...]:
    """The owning coverage representation for verified native closed bars."""
    return (
        f"canonical_fact_count={fact_count}",
        f"bar_grid_count={grid_count}",
        f"closed_external_bar={str(semantic_valid).lower()}",
    )


def only_build_seal(
    revision: OnlyMarketDataRevision,
    manifest: OnlyCoverageManifest,
    *,
    sealed_at: datetime,
) -> OnlyMarketDataSeal:
    if manifest.coverage_status is not OnlyCoverageStatus.COMPLETE or manifest.issues:
        raise OnlyMarketDataSealError("REVISION_COVERAGE_NOT_SEALABLE")
    checks = _REQUIRED_SEAL_CHECKS + (("BAR_TEMPORAL_GRID_VERIFIED",) if manifest.scope.data_kind == "BAR" else ())
    fingerprint = only_canonical_fingerprint(
        {"revision": revision.fingerprint, "manifest": manifest.fingerprint, "checks": checks}
    )
    return OnlyMarketDataSeal(f"seal:{fingerprint}", revision.revision_id, revision.fingerprint, checks, sealed_at)


def only_verify_revision_authority(
    revision: OnlyMarketDataRevision,
    manifest: OnlyCoverageManifest,
    seal: OnlyMarketDataSeal,
) -> None:
    """Verify complete sealed authority using catalog metadata alone."""
    try:
        valid = (
            manifest.manifest_id == revision.manifest_id
            and manifest.scope == revision.scope
            and manifest.segment_refs == revision.segment_refs
            and manifest.coverage_status is OnlyCoverageStatus.COMPLETE
            and not manifest.issues
            and not manifest.gaps
            and OnlyCoverageManifest.build(
                manifest.scope,
                manifest.segment_refs,
                coverage_status=manifest.coverage_status,
                proof=manifest.proof,
                issues=manifest.issues,
                gaps=manifest.gaps,
            )
            == manifest
            and OnlyMarketDataRevision.build(
                manifest,
                normalizers=revision.normalizers,
                creation_reason=revision.creation_reason,
                parent_revision_id=revision.parent_revision_id,
            )
            == revision
            and only_build_seal(revision, manifest, sealed_at=seal.sealed_at) == seal
        )
    except (TypeError, ValueError) as exc:
        raise OnlyMarketDataSealError("MARKET_DATA_REVISION_EVIDENCE_INVALID") from exc
    if not valid:
        raise OnlyMarketDataSealError("MARKET_DATA_REVISION_EVIDENCE_INVALID")
