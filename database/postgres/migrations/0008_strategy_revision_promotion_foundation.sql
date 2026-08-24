ALTER TABLE research_deployment_semantic_store_binding
    ADD CONSTRAINT research_deployment_semantic_store_id_unique UNIQUE (semantic_store_id);

CREATE TABLE strategy_catalog (
    strategy_fingerprint TEXT PRIMARY KEY CHECK (strategy_fingerprint ~ '^[0-9a-f]{64}$'),
    semantic_namespace_id UUID NOT NULL REFERENCES research_deployment_semantic_store_binding (semantic_store_id),
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    display_name TEXT,
    catalog_family TEXT
);

CREATE TABLE strategy_freeze_record (
    freeze_record_fingerprint TEXT PRIMARY KEY CHECK (freeze_record_fingerprint ~ '^[0-9a-f]{64}$'),
    candidate_fingerprint TEXT NOT NULL CHECK (candidate_fingerprint ~ '^[0-9a-f]{64}$'),
    research_result_fingerprint TEXT NOT NULL CHECK (research_result_fingerprint ~ '^[0-9a-f]{64}$'),
    strategy_fingerprint TEXT NOT NULL REFERENCES strategy_catalog (strategy_fingerprint),
    admission_evidence_fingerprint TEXT NOT NULL CHECK (admission_evidence_fingerprint ~ '^[0-9a-f]{64}$'),
    actor TEXT NOT NULL CHECK (btrim(actor) <> ''),
    created_at TIMESTAMPTZ NOT NULL,
    comment TEXT,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    UNIQUE (candidate_fingerprint, research_result_fingerprint, strategy_fingerprint)
);

CREATE TABLE strategy_promotion_record (
    promotion_record_fingerprint TEXT PRIMARY KEY CHECK (promotion_record_fingerprint ~ '^[0-9a-f]{64}$'),
    strategy_fingerprint TEXT NOT NULL REFERENCES strategy_catalog (strategy_fingerprint),
    from_stage TEXT NOT NULL CHECK (from_stage IN ('RESEARCH', 'BACKTEST', 'SIM')),
    to_stage TEXT NOT NULL CHECK (to_stage IN ('BACKTEST', 'SIM', 'LIVE_ELIGIBLE')),
    evidence_fingerprints TEXT[] NOT NULL CHECK (cardinality(evidence_fingerprints) > 0),
    previous_record_fingerprint TEXT REFERENCES strategy_promotion_record (promotion_record_fingerprint),
    decision TEXT NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    actor TEXT NOT NULL CHECK (btrim(actor) <> ''),
    recorded_at TIMESTAMPTZ NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    UNIQUE (strategy_fingerprint, previous_record_fingerprint)
);

CREATE UNIQUE INDEX strategy_promotion_first_record
    ON strategy_promotion_record (strategy_fingerprint)
    WHERE previous_record_fingerprint IS NULL;

CREATE INDEX strategy_freeze_candidate_idx ON strategy_freeze_record (candidate_fingerprint);
CREATE INDEX strategy_promotion_strategy_idx ON strategy_promotion_record (strategy_fingerprint, recorded_at);
