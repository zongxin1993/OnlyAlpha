"""Layered canonical Factor-Pair Statistics identities."""

from __future__ import annotations

from onlyalpha.canonical import only_canonical_fingerprint

from .definition import OnlyResearchFactorPairStatisticsDefinition
from .reference import OnlyResearchFactorPairOperand

RESEARCH_FACTOR_PAIR_STATISTICS_DOMAIN = "RESEARCH_FACTOR_PAIR_STATISTICS"
RESEARCH_FACTOR_PAIR_STATISTICS_IDENTITY_SCHEMA_VERSION = 1
RESEARCH_FACTOR_PAIR_STATISTICS_RESULT_SCHEMA_VERSION = 1


def only_research_factor_pair_statistics_fingerprint(
    dataset_snapshot_fingerprint: str,
    first_operand: OnlyResearchFactorPairOperand,
    second_operand: OnlyResearchFactorPairOperand,
    definition: OnlyResearchFactorPairStatisticsDefinition,
) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_FACTOR_PAIR_STATISTICS_IDENTITY_SCHEMA_VERSION,
            "domain": RESEARCH_FACTOR_PAIR_STATISTICS_DOMAIN,
            "dataset_snapshot_fingerprint": dataset_snapshot_fingerprint,
            "first_operand": first_operand.to_dict(),
            "second_operand": second_operand.to_dict(),
            "definition": definition.to_dict(),
        }
    )


def only_research_factor_pair_result_content_fingerprint(
    first_calculation_result_fingerprint: str,
    second_calculation_result_fingerprint: str,
    rows: tuple[object, ...],
) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_FACTOR_PAIR_STATISTICS_RESULT_SCHEMA_VERSION,
            "domain": RESEARCH_FACTOR_PAIR_STATISTICS_DOMAIN,
            "first_calculation_result_fingerprint": first_calculation_result_fingerprint,
            "second_calculation_result_fingerprint": second_calculation_result_fingerprint,
            "rows": rows,
        }
    )


def only_research_factor_pair_result_fingerprint(statistics_fingerprint: str, result_content_fingerprint: str) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_FACTOR_PAIR_STATISTICS_RESULT_SCHEMA_VERSION,
            "domain": RESEARCH_FACTOR_PAIR_STATISTICS_DOMAIN,
            "statistics_fingerprint": statistics_fingerprint,
            "result_content_fingerprint": result_content_fingerprint,
        }
    )
