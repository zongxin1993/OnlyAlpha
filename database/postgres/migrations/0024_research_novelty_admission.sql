CREATE TABLE research_novelty_admission (
    command_id UUID PRIMARY KEY REFERENCES product_command_admission(command_id),
    command_fingerprint TEXT NOT NULL CHECK (command_fingerprint ~ '^[0-9a-f]{64}$'),
    novelty_decision_fingerprint TEXT NOT NULL CHECK (novelty_decision_fingerprint ~ '^[0-9a-f]{64}$'),
    canonical_intent_fingerprint TEXT NOT NULL CHECK (canonical_intent_fingerprint ~ '^[0-9a-f]{64}$'),
    evaluation_subject_fingerprint TEXT NOT NULL CHECK (evaluation_subject_fingerprint ~ '^[0-9a-f]{64}$'),
    decision_time_proof_fingerprint TEXT NOT NULL CHECK (decision_time_proof_fingerprint ~ '^[0-9a-f]{64}$'),
    action_time_proof_fingerprint TEXT NOT NULL CHECK (action_time_proof_fingerprint ~ '^[0-9a-f]{64}$'),
    action_source_manifest_fingerprint TEXT NOT NULL CHECK (action_source_manifest_fingerprint ~ '^[0-9a-f]{64}$'),
    same_subject_guard_key TEXT NOT NULL CHECK (same_subject_guard_key ~ '^[0-9a-f]{64}$'),
    runtime_work_id TEXT NOT NULL,
    run_id UUID NOT NULL UNIQUE REFERENCES research_run(run_id),
    admission_fingerprint TEXT NOT NULL UNIQUE CHECK (admission_fingerprint ~ '^[0-9a-f]{64}$'),
    schema_version SMALLINT NOT NULL CHECK (schema_version = 1),
    CHECK (runtime_work_id = run_id::text),
    CONSTRAINT research_novelty_admission_command_identity UNIQUE (
        command_id, command_fingerprint
    )
);

CREATE INDEX research_novelty_admission_subject_index
    ON research_novelty_admission (evaluation_subject_fingerprint, run_id);

CREATE TRIGGER research_novelty_admission_immutable_trigger
    BEFORE UPDATE OR DELETE OR TRUNCATE ON research_novelty_admission
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_history_immutable();
