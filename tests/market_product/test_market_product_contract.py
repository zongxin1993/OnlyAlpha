from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
from typing import Never

import pytest

from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.fee.market_pack import OnlyMarketFeePack
from onlyalpha.identity import only_identity_fingerprint
from onlyalpha.plugin.api import (
    OnlyCanonicalMarketProductConfig,
    OnlyDuplicateMarketProductPluginError,
    OnlyInvalidMarketProductConfigurationError,
    OnlyMarketPolicyCompilationRequest,
    OnlyMarketProductAuthorityConflictError,
    OnlyMarketProductAuthorityIdentity,
    OnlyMarketProductConfig,
    OnlyMarketProductFactoryRegistry,
    OnlyMarketProductId,
    OnlyMarketProductIdentity,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductResolutionError,
    OnlyMarketProductVersion,
    OnlyResolvedMarketProductBinding,
    OnlyUnknownMarketProductPluginError,
    OnlyUnsupportedMarketProductError,
    OnlyUnsupportedMarketProductVersionError,
)

PLUGIN_A = OnlyMarketProductPluginId("onlyalpha-market-test-a")
PLUGIN_B = OnlyMarketProductPluginId("onlyalpha-market-test-b")
PRODUCT = OnlyMarketProductId("TEST_CASH")
VERSION_1 = OnlyMarketProductVersion("1")
VERSION_2 = OnlyMarketProductVersion("2")


def _authority(kind: str, authority_id: str, version: str) -> OnlyMarketProductAuthorityIdentity:
    return OnlyMarketProductAuthorityIdentity(
        kind,
        authority_id,
        version,
        only_identity_fingerprint((kind, authority_id, version)),
    )


@dataclass(frozen=True, slots=True)
class OnlyTestReference:
    content_fingerprint: str


@dataclass(frozen=True, slots=True)
class OnlyTestReferenceAuthority:
    identity: OnlyMarketProductAuthorityIdentity

    def resolve(self, instrument_id: OnlyInstrumentId, trading_day: OnlyTradingDay) -> OnlyTestReference:
        return OnlyTestReference(only_identity_fingerprint((str(instrument_id), str(trading_day))))


@dataclass(frozen=True, slots=True)
class OnlyTestPolicyCompiler:
    identity: OnlyMarketProductAuthorityIdentity

    def compile(self, request: OnlyMarketPolicyCompilationRequest) -> Never:
        del request
        raise AssertionError("contract test does not execute concrete market semantics")


@dataclass(frozen=True, slots=True)
class OnlyTestResources:
    references: dict[str, OnlyTestReferenceAuthority]
    fee_pack: OnlyMarketFeePack

    def require_reference_authority(self, resource_id: str) -> OnlyTestReferenceAuthority:
        if resource_id == "ambiguous":
            raise OnlyMarketProductResolutionError(
                "AMBIGUOUS_MARKET_REFERENCE_AUTHORITY", "more than one authority matched"
            )
        try:
            return self.references[resource_id]
        except KeyError as exc:
            raise OnlyMarketProductResolutionError("MARKET_REFERENCE_AUTHORITY_NOT_FOUND", resource_id) from exc

    def require_market_fee_pack(self, pack_id: str, pack_version: str) -> OnlyMarketFeePack:
        if (pack_id, pack_version) != (self.fee_pack.pack_id, self.fee_pack.pack_version):
            raise OnlyMarketProductResolutionError("MARKET_FEE_PACK_NOT_FOUND", f"{pack_id}@{pack_version}")
        return self.fee_pack


@dataclass(frozen=True, slots=True)
class OnlyTestMarketProductFactory:
    plugin_id: OnlyMarketProductPluginId
    compiler: OnlyTestPolicyCompiler

    def resolve(
        self,
        config: OnlyMarketProductConfig,
        context: OnlyMarketProductResolutionContext,
    ) -> OnlyResolvedMarketProductBinding:
        if config.product_id != PRODUCT:
            raise OnlyUnsupportedMarketProductError("UNSUPPORTED_MARKET_PRODUCT", str(config.product_id))
        if config.product_version not in {VERSION_1, VERSION_2}:
            raise OnlyUnsupportedMarketProductVersionError(
                "UNSUPPORTED_MARKET_PRODUCT_VERSION", str(config.product_version)
            )
        values = config.config.values
        unknown = sorted(set(values) - {"alternative", "invalid", "price_increment", "reference_resource"})
        if unknown:
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_MARKET_PRODUCT_CONFIGURATION",
                f"unknown configuration field: {unknown[0]}",
            )
        if values.get("invalid") is True:
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_MARKET_PRODUCT_CONFIGURATION", "invalid test payload"
            )
        reference_id = values.get("reference_resource", "reference-v1")
        if not isinstance(reference_id, str):
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_MARKET_PRODUCT_CONFIGURATION", "reference_resource must be a string"
            )
        reference = context.resources.require_reference_authority(reference_id)
        fee_pack = context.resources.require_market_fee_pack("test-fees", "1")
        product_identity = OnlyMarketProductIdentity(config.product_id, config.product_version)
        effective_config = {"price_increment": values.get("price_increment", "0.01")}
        return OnlyResolvedMarketProductBinding.create(
            product_identity=product_identity,
            provider_plugin_id=self.plugin_id,
            reference_authority=reference,
            policy_compiler=self.compiler,
            market_fee_pack=fee_pack,
            effective_config_fingerprint=only_identity_fingerprint(effective_config),
        )


def _config(
    *,
    plugin_id: OnlyMarketProductPluginId = PLUGIN_A,
    product_id: OnlyMarketProductId = PRODUCT,
    version: OnlyMarketProductVersion = VERSION_1,
    values: dict[str, object] | None = None,
) -> OnlyMarketProductConfig:
    return OnlyMarketProductConfig(
        plugin_id,
        product_id,
        version,
        OnlyCanonicalMarketProductConfig(values or {}),
    )


@pytest.fixture
def authorities() -> tuple[OnlyTestMarketProductFactory, OnlyMarketProductResolutionContext]:
    fee_pack = OnlyMarketFeePack.create(
        pack_id="test-fees",
        pack_version="1",
        compatible_market_products=("TEST_CASH",),
        schedules=(),
    )
    references = {
        "reference-v1": OnlyTestReferenceAuthority(_authority("REFERENCE", "test-reference", "1")),
        "reference-v1-conflict": OnlyTestReferenceAuthority(
            OnlyMarketProductAuthorityIdentity(
                "REFERENCE",
                "test-reference",
                "1",
                only_identity_fingerprint(("different", "semantics")),
            )
        ),
        "reference-v2": OnlyTestReferenceAuthority(_authority("REFERENCE", "test-reference", "2")),
    }
    references["different-locator-same-reference"] = references["reference-v1"]
    compiler = OnlyTestPolicyCompiler(_authority("POLICY_COMPILER", "test-policy", "1"))
    return OnlyTestMarketProductFactory(PLUGIN_A, compiler), OnlyMarketProductResolutionContext(
        OnlyTestResources(references, fee_pack)
    )


def test_registry_resolves_by_explicit_plugin_id_and_is_fail_closed(
    authorities: tuple[OnlyTestMarketProductFactory, OnlyMarketProductResolutionContext],
) -> None:
    factory, context = authorities
    registry = OnlyMarketProductFactoryRegistry()
    registry.register(factory)
    registry.register(factory)
    binding = registry.resolve(_config(), context)
    assert registry.require(PLUGIN_A) is factory
    assert binding.product_identity.canonical_name == "TEST_CASH@1"
    with pytest.raises(OnlyUnknownMarketProductPluginError, match="MARKET_PRODUCT_PLUGIN_NOT_REGISTERED"):
        registry.resolve(_config(plugin_id=PLUGIN_B), context)


def test_registry_rejects_conflicting_and_invalid_factory_identity(
    authorities: tuple[OnlyTestMarketProductFactory, OnlyMarketProductResolutionContext],
) -> None:
    factory, _ = authorities
    registry = OnlyMarketProductFactoryRegistry()
    registry.register(factory)
    with pytest.raises(OnlyDuplicateMarketProductPluginError, match="MARKET_PRODUCT_PLUGIN_CONFLICT"):
        registry.register(OnlyTestMarketProductFactory(PLUGIN_A, factory.compiler))

    @dataclass(frozen=True, slots=True)
    class InvalidFactory:
        plugin_id: str = "not-a-typed-id"

    with pytest.raises(OnlyMarketProductResolutionError, match="INVALID_MARKET_PRODUCT_FACTORY_IDENTITY"):
        registry.register(InvalidFactory())  # type: ignore[arg-type]


def test_registry_rejects_factory_identity_that_changes_after_registration(
    authorities: tuple[OnlyTestMarketProductFactory, OnlyMarketProductResolutionContext],
) -> None:
    factory, context = authorities

    class MismatchedFactory:
        reads = 0

        @property
        def plugin_id(self) -> OnlyMarketProductPluginId:
            self.reads += 1
            return PLUGIN_A if self.reads == 1 else PLUGIN_B

        def resolve(
            self,
            config: OnlyMarketProductConfig,
            resolution_context: OnlyMarketProductResolutionContext,
        ) -> OnlyResolvedMarketProductBinding:
            return factory.resolve(config, resolution_context)

    registry = OnlyMarketProductFactoryRegistry()
    registry.register(MismatchedFactory())
    with pytest.raises(OnlyMarketProductResolutionError, match="MARKET_PRODUCT_FACTORY_IDENTITY_MISMATCH"):
        registry.resolve(_config(), context)


def test_registration_order_does_not_change_selected_factory_semantics(
    authorities: tuple[OnlyTestMarketProductFactory, OnlyMarketProductResolutionContext],
) -> None:
    factory_a, context = authorities
    factory_b = OnlyTestMarketProductFactory(PLUGIN_B, factory_a.compiler)
    first = OnlyMarketProductFactoryRegistry()
    second = OnlyMarketProductFactoryRegistry()
    first.register(factory_a)
    first.register(factory_b)
    second.register(factory_b)
    second.register(factory_a)
    assert (
        first.resolve(_config(), context).composition_identity
        == second.resolve(_config(), context).composition_identity
    )
    assert first.plugin_ids() == second.plugin_ids() == (PLUGIN_A, PLUGIN_B)


def test_registry_rejects_same_authority_version_with_changed_semantics(
    authorities: tuple[OnlyTestMarketProductFactory, OnlyMarketProductResolutionContext],
) -> None:
    factory, context = authorities
    registry = OnlyMarketProductFactoryRegistry()
    registry.register(factory)
    first = registry.resolve(_config(values={"reference_resource": "reference-v1"}), context)
    repeated = registry.resolve(_config(values={"reference_resource": "reference-v1"}), context)
    assert first.composition_identity == repeated.composition_identity
    with pytest.raises(
        OnlyMarketProductAuthorityConflictError,
        match="MARKET_PRODUCT_AUTHORITY_VERSION_CONFLICT",
    ):
        registry.resolve(_config(values={"reference_resource": "reference-v1-conflict"}), context)


def test_registry_rejects_same_product_version_with_different_compiler_or_fee_definition(
    authorities: tuple[OnlyTestMarketProductFactory, OnlyMarketProductResolutionContext],
) -> None:
    factory, context = authorities
    alternative = OnlyTestMarketProductFactory(
        PLUGIN_A,
        OnlyTestPolicyCompiler(_authority("POLICY_COMPILER", "alternative-policy", "1")),
    )

    class SwitchingFactory:
        plugin_id = PLUGIN_A

        def resolve(
            self,
            config: OnlyMarketProductConfig,
            resolution_context: OnlyMarketProductResolutionContext,
        ) -> OnlyResolvedMarketProductBinding:
            selected = alternative if config.config.values.get("alternative") is True else factory
            return selected.resolve(config, resolution_context)

    registry = OnlyMarketProductFactoryRegistry()
    registry.register(SwitchingFactory())
    registry.resolve(_config(), context)
    with pytest.raises(
        OnlyMarketProductAuthorityConflictError,
        match="MARKET_PRODUCT_VERSION_SEMANTICS_CONFLICT",
    ):
        registry.resolve(_config(values={"alternative": True}), context)


def test_binding_and_identities_are_immutable_and_authority_consistent(
    authorities: tuple[OnlyTestMarketProductFactory, OnlyMarketProductResolutionContext],
) -> None:
    factory, context = authorities
    binding = factory.resolve(_config(), context)
    with pytest.raises(FrozenInstanceError):
        binding.product_identity = OnlyMarketProductIdentity(PRODUCT, VERSION_2)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        binding.reference_authority.identity = _authority("REFERENCE", "other", "1")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        binding.composition_identity.fingerprint = "0" * 64  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        binding.market_fee_pack.pack_version = "2"  # type: ignore[misc]


def test_config_envelope_is_deeply_immutable_and_rejects_non_canonical_objects() -> None:
    config = OnlyCanonicalMarketProductConfig({"nested": {"items": ["a", "b"]}})
    nested = config.values["nested"]
    assert not isinstance(nested, str)
    with pytest.raises(TypeError):
        config.values["new"] = "value"  # type: ignore[index]
    with pytest.raises(TypeError, match="unsupported Market Product config value"):
        OnlyCanonicalMarketProductConfig({"object": object()})  # type: ignore[dict-item]


def test_composition_identity_uses_effective_authorities_not_raw_payload(
    authorities: tuple[OnlyTestMarketProductFactory, OnlyMarketProductResolutionContext],
) -> None:
    factory, context = authorities
    plain = factory.resolve(_config(values={"price_increment": "0.01"}), context)
    reordered_raw_fields = factory.resolve(
        _config(values={"reference_resource": "reference-v1", "price_increment": "0.01"}), context
    )
    changed_effective_config = factory.resolve(_config(values={"price_increment": "0.02"}), context)
    changed_reference = factory.resolve(_config(values={"reference_resource": "reference-v2"}), context)
    changed_locator = factory.resolve(
        _config(values={"reference_resource": "different-locator-same-reference"}), context
    )
    changed_version = factory.resolve(_config(version=VERSION_2), context)
    changed_compiler = OnlyTestMarketProductFactory(
        PLUGIN_A,
        OnlyTestPolicyCompiler(_authority("POLICY_COMPILER", "test-policy", "2")),
    ).resolve(_config(), context)
    changed_fee = OnlyMarketFeePack.create(
        pack_id="test-fees",
        pack_version="1",
        compatible_market_products=("DIFFERENT_PRODUCT",),
        schedules=(),
    )
    changed_fee_context = OnlyMarketProductResolutionContext(
        OnlyTestResources(context.resources.references, changed_fee)  # type: ignore[attr-defined]
    )
    changed_fee_binding = factory.resolve(_config(), changed_fee_context)
    repeated = factory.resolve(_config(values={"price_increment": "0.01"}), context)

    assert plain.composition_identity == repeated.composition_identity
    assert plain.composition_identity == reordered_raw_fields.composition_identity
    assert plain.composition_identity == changed_locator.composition_identity
    assert plain.composition_identity != changed_effective_config.composition_identity
    assert plain.composition_identity != changed_reference.composition_identity
    assert plain.composition_identity != changed_version.composition_identity
    assert plain.composition_identity != changed_compiler.composition_identity
    assert plain.composition_identity != changed_fee_binding.composition_identity


def test_runtime_label_is_not_an_input_to_market_composition_identity(
    authorities: tuple[OnlyTestMarketProductFactory, OnlyMarketProductResolutionContext],
) -> None:
    factory, context = authorities
    binding = factory.resolve(_config(), context)
    fingerprints = {
        runtime_label: binding.composition_identity.fingerprint
        for runtime_label in ("RESEARCH", "BACKTEST", "SIM", "LIVE")
    }
    assert len(set(fingerprints.values())) == 1


@pytest.mark.parametrize(
    ("config", "error", "code"),
    [
        (
            _config(product_id=OnlyMarketProductId("UNKNOWN")),
            OnlyUnsupportedMarketProductError,
            "UNSUPPORTED_MARKET_PRODUCT",
        ),
        (
            _config(version=OnlyMarketProductVersion("99")),
            OnlyUnsupportedMarketProductVersionError,
            "UNSUPPORTED_MARKET_PRODUCT_VERSION",
        ),
        (
            _config(values={"invalid": True}),
            OnlyInvalidMarketProductConfigurationError,
            "INVALID_MARKET_PRODUCT_CONFIGURATION",
        ),
        (
            _config(values={"unknown_option": 1}),
            OnlyInvalidMarketProductConfigurationError,
            "INVALID_MARKET_PRODUCT_CONFIGURATION",
        ),
        (
            _config(values={"reference_resource": "missing"}),
            OnlyMarketProductResolutionError,
            "MARKET_REFERENCE_AUTHORITY_NOT_FOUND",
        ),
        (
            _config(values={"reference_resource": "ambiguous"}),
            OnlyMarketProductResolutionError,
            "AMBIGUOUS_MARKET_REFERENCE_AUTHORITY",
        ),
    ],
)
def test_factory_rejects_unsupported_invalid_missing_and_ambiguous_resolution(
    authorities: tuple[OnlyTestMarketProductFactory, OnlyMarketProductResolutionContext],
    config: OnlyMarketProductConfig,
    error: type[Exception],
    code: str,
) -> None:
    factory, context = authorities
    with pytest.raises(error, match=code):
        factory.resolve(config, context)
