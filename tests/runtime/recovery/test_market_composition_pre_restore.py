from __future__ import annotations

import pytest

from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.fee.models import OnlyMarketFeePackIdentity
from onlyalpha.identity import only_identity_fingerprint
from onlyalpha.market.product import (
    OnlyMarketProductAuthorityIdentity,
    OnlyMarketProductCompositionIdentity,
    OnlyMarketProductId,
    OnlyMarketProductIdentity,
    OnlyMarketProductVersion,
)
from onlyalpha.runtime.checkpoint.model import OnlyBacktestReplayCursor
from onlyalpha.runtime.checkpoint.participant import OnlyJsonRuntimeCheckpointParticipant
from onlyalpha.runtime.checkpoint.registry import OnlyRuntimeCheckpointParticipantRegistry
from onlyalpha.runtime.checkpoint.service import OnlyRuntimeCheckpointService
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore
from onlyalpha.runtime.recovery.orchestrator import OnlyRuntimeRecoveryOrchestrator


def _authority(kind: str, authority_id: str, version: str, semantics: str) -> OnlyMarketProductAuthorityIdentity:
    return OnlyMarketProductAuthorityIdentity(
        kind,
        authority_id,
        version,
        only_identity_fingerprint((semantics,)),
    )


def _composition(
    *,
    product_version: str = "1",
    reference_semantics: str = "reference-a",
    compiler_version: str = "1",
    fee_version: str = "1",
    effective_config: str = "config-a",
) -> str:
    identity = OnlyMarketProductCompositionIdentity.create(
        product_identity=OnlyMarketProductIdentity(
            OnlyMarketProductId("TEST_CASH"),
            OnlyMarketProductVersion(product_version),
        ),
        reference_authority=_authority("REFERENCE", "test-reference", "1", reference_semantics),
        policy_compiler=_authority("POLICY_COMPILER", "test-compiler", compiler_version, compiler_version),
        market_fee_pack=OnlyMarketFeePackIdentity(
            "test-fees",
            fee_version,
            only_identity_fingerprint(("fees", fee_version)),
        ),
        effective_config_fingerprint=only_identity_fingerprint((effective_config,)),
    )
    return identity.fingerprint


def _assert_pre_restore_rejected(
    *,
    checkpoint_composition: str,
    runtime_composition: str,
    checkpoint_config: str = "config",
    runtime_config: str = "config",
    error: str,
) -> None:
    runtime_id = OnlyRuntimeId("runtime")
    restored: list[object] = []
    registry = OnlyRuntimeCheckpointParticipantRegistry()
    registry.register(
        OnlyJsonRuntimeCheckpointParticipant(
            "mutable.authority",
            1,
            lambda: {"value": 1},
            restored.append,
        )
    )
    store = OnlyInMemoryRuntimePersistenceStore()
    service = OnlyRuntimeCheckpointService(
        runtime_id=runtime_id,
        config_fingerprint=checkpoint_config,
        market_composition_fingerprint=checkpoint_composition,
        registry=registry,
        write_port=store,
        query_port=store,
        transaction_query=store,
        outbox_port=store,
        retain_last=1,
    )
    cursor = OnlyBacktestReplayCursor(
        OnlyMarketDataSourceId("source"),
        OnlyDataVersion("version"),
        None,
        0,
        None,
        0,
    )
    service.create(cursor, OnlyTimestamp.from_unix_nanos(1))
    orchestrator = OnlyRuntimeRecoveryOrchestrator(
        runtime_id=runtime_id,
        config_fingerprint=runtime_config,
        market_composition_fingerprint=runtime_composition,
        participant_registry=registry,
        checkpoint_query=store,
        transaction_query=store,
        causal_replay=lambda checkpoint, session: pytest.fail(
            f"causal replay must not run for {checkpoint} / {session}"
        ),
    )

    with pytest.raises(RuntimeError, match=error):
        orchestrator.recover()
    assert restored == []


@pytest.mark.parametrize(
    "runtime_composition",
    (
        _composition(reference_semantics="reference-b"),
        _composition(compiler_version="2"),
        _composition(fee_version="2"),
        _composition(effective_config="config-b"),
        _composition(product_version="2"),
    ),
    ids=("reference", "compiler", "fee", "effective-config", "product-version"),
)
def test_market_composition_mismatch_matrix_fails_before_any_mutable_restore(
    runtime_composition: str,
) -> None:
    _assert_pre_restore_rejected(
        checkpoint_composition=_composition(),
        runtime_composition=runtime_composition,
        error="CHECKPOINT_MARKET_COMPOSITION_FINGERPRINT_MISMATCH",
    )


def test_provider_environment_mismatch_fails_before_any_mutable_restore() -> None:
    composition = _composition()
    _assert_pre_restore_rejected(
        checkpoint_composition=composition,
        runtime_composition=composition,
        checkpoint_config="provider-a-environment",
        runtime_config="provider-b-environment",
        error="CHECKPOINT_CONFIG_FINGERPRINT_MISMATCH",
    )
