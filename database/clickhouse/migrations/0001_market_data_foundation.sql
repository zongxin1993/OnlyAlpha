CREATE TABLE IF NOT EXISTS onlyalpha_schema_migration
(
    migration_id String,
    checksum_sha256 FixedString(64),
    applied_at DateTime64(9, 'UTC')
)
ENGINE = MergeTree
ORDER BY migration_id
SETTINGS storage_policy = '{storage_policy}';

CREATE TABLE IF NOT EXISTS market_raw_event
(
    raw_event_id String,
    source_id String,
    provider LowCardinality(String),
    venue LowCardinality(String),
    market LowCardinality(String),
    stream LowCardinality(String),
    capture_session_id String,
    segment_id String,
    segment_content_hash FixedString(64),
    record_ordinal UInt64,
    provider_event_type LowCardinality(String),
    provider_event_id Nullable(String),
    provider_sequence Nullable(Int64),
    ts_event_ns Nullable(Int64),
    ts_receive_ns Int64,
    ts_ingest_ns Int64,
    payload_codec LowCardinality(String),
    provider_schema String,
    provenance LowCardinality(String),
    raw_payload_base64 String,
    raw_sha256 FixedString(64),
    record_hash FixedString(64)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(toDateTime64(ts_receive_ns / 1000000000, 9, 'UTC'))
ORDER BY (source_id, segment_id, record_ordinal, raw_event_id)
SETTINGS storage_policy = '{storage_policy}';

CREATE TABLE IF NOT EXISTS market_trade
(
    canonical_fact_id String,
    source_id String,
    instrument_id String,
    segment_id String,
    segment_content_hash FixedString(64),
    capture_session_id String,
    raw_event_id String,
    provider_event_id Nullable(String),
    provider_sequence Nullable(Int64),
    ts_event_ns Int64,
    ts_receive_ns Int64,
    ts_ingest_ns Int64,
    price Decimal256(18),
    price_precision UInt8,
    quantity Decimal256(18),
    quantity_precision UInt8,
    aggressor_side Nullable(String),
    provenance LowCardinality(String),
    quality_state LowCardinality(String),
    canonical_payload_json String,
    canonical_payload_hash FixedString(64),
    normalizer_id String,
    normalizer_version String,
    record_hash FixedString(64)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(toDateTime64(ts_event_ns / 1000000000, 9, 'UTC'))
ORDER BY (source_id, instrument_id, ts_event_ns, canonical_fact_id, raw_event_id)
SETTINGS storage_policy = '{storage_policy}';

CREATE TABLE IF NOT EXISTS market_bar
(
    canonical_fact_id String,
    source_id String,
    instrument_id String,
    segment_id String,
    segment_content_hash FixedString(64),
    capture_session_id String,
    raw_event_id String,
    ts_event_ns Int64,
    ts_receive_ns Int64,
    ts_ingest_ns Int64,
    bar_start_ns Int64,
    bar_end_ns Int64,
    bar_type_json String,
    open Decimal256(18), high Decimal256(18), low Decimal256(18), close Decimal256(18),
    price_precision UInt8,
    volume Decimal256(18), quantity_precision UInt8,
    quote_volume Nullable(Decimal256(18)),
    trade_count Nullable(UInt64),
    provenance LowCardinality(String),
    quality_state LowCardinality(String),
    canonical_payload_json String,
    canonical_payload_hash FixedString(64),
    normalizer_id String,
    normalizer_version String,
    record_hash FixedString(64)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(toDateTime64(ts_event_ns / 1000000000, 9, 'UTC'))
ORDER BY (source_id, instrument_id, bar_start_ns, canonical_fact_id, raw_event_id)
SETTINGS storage_policy = '{storage_policy}';

CREATE TABLE IF NOT EXISTS market_reference_price
(
    canonical_fact_id String,
    source_id String,
    instrument_id String,
    segment_id String,
    segment_content_hash FixedString(64),
    capture_session_id String,
    raw_event_id String,
    ts_event_ns Int64,
    ts_receive_ns Int64,
    ts_ingest_ns Int64,
    reference_kind LowCardinality(String),
    price Nullable(Decimal256(18)),
    price_precision Nullable(UInt8),
    provenance LowCardinality(String),
    quality_state LowCardinality(String),
    canonical_payload_json String,
    canonical_payload_hash FixedString(64),
    normalizer_id String,
    normalizer_version String,
    record_hash FixedString(64)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(toDateTime64(ts_event_ns / 1000000000, 9, 'UTC'))
ORDER BY (source_id, instrument_id, ts_event_ns, canonical_fact_id, raw_event_id)
SETTINGS storage_policy = '{storage_policy}';
