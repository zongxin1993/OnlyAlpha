ALTER TABLE research_novelty_admission
    ADD COLUMN decision_group_fingerprint TEXT CHECK (decision_group_fingerprint ~ '^[0-9a-f]{64}$'),
    ADD COLUMN subject_set_fingerprint TEXT CHECK (subject_set_fingerprint ~ '^[0-9a-f]{64}$');

ALTER TABLE research_novelty_admission
    ALTER COLUMN novelty_decision_fingerprint DROP NOT NULL,
    ALTER COLUMN canonical_intent_fingerprint DROP NOT NULL,
    ALTER COLUMN evaluation_subject_fingerprint DROP NOT NULL,
    ALTER COLUMN decision_time_proof_fingerprint DROP NOT NULL,
    ALTER COLUMN action_time_proof_fingerprint DROP NOT NULL,
    ALTER COLUMN same_subject_guard_key DROP NOT NULL,
    DROP CONSTRAINT research_novelty_admission_schema_version_check,
    ADD CONSTRAINT research_novelty_admission_schema_version_check CHECK (schema_version IN (1, 2)),
    ADD CONSTRAINT research_novelty_admission_version_shape_check CHECK (
        (schema_version = 1
            AND novelty_decision_fingerprint IS NOT NULL
            AND canonical_intent_fingerprint IS NOT NULL
            AND evaluation_subject_fingerprint IS NOT NULL
            AND decision_time_proof_fingerprint IS NOT NULL
            AND action_time_proof_fingerprint IS NOT NULL
            AND same_subject_guard_key IS NOT NULL
            AND decision_group_fingerprint IS NULL
            AND subject_set_fingerprint IS NULL)
        OR
        (schema_version = 2
            AND novelty_decision_fingerprint IS NULL
            AND canonical_intent_fingerprint IS NULL
            AND evaluation_subject_fingerprint IS NULL
            AND decision_time_proof_fingerprint IS NULL
            AND action_time_proof_fingerprint IS NULL
            AND same_subject_guard_key IS NULL
            AND decision_group_fingerprint IS NOT NULL
            AND subject_set_fingerprint IS NOT NULL)
    ),
    ADD CONSTRAINT research_novelty_admission_exact_parent_key UNIQUE (command_id, admission_fingerprint);

CREATE TABLE research_novelty_admission_subject (
    command_id UUID NOT NULL,
    admission_fingerprint TEXT NOT NULL CHECK (admission_fingerprint ~ '^[0-9a-f]{64}$'),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    evaluation_subject_fingerprint TEXT NOT NULL CHECK (evaluation_subject_fingerprint ~ '^[0-9a-f]{64}$'),
    novelty_decision_fingerprint TEXT NOT NULL CHECK (novelty_decision_fingerprint ~ '^[0-9a-f]{64}$'),
    canonical_intent_fingerprint TEXT NOT NULL CHECK (canonical_intent_fingerprint ~ '^[0-9a-f]{64}$'),
    decision_time_proof_fingerprint TEXT NOT NULL CHECK (decision_time_proof_fingerprint ~ '^[0-9a-f]{64}$'),
    action_time_proof_fingerprint TEXT NOT NULL CHECK (action_time_proof_fingerprint ~ '^[0-9a-f]{64}$'),
    same_subject_guard_key TEXT NOT NULL CHECK (same_subject_guard_key ~ '^[0-9a-f]{64}$'),
    schema_version SMALLINT NOT NULL CHECK (schema_version = 1),
    PRIMARY KEY (command_id, ordinal),
    UNIQUE (command_id, evaluation_subject_fingerprint),
    FOREIGN KEY (command_id, admission_fingerprint)
        REFERENCES research_novelty_admission(command_id, admission_fingerprint)
);

CREATE INDEX research_novelty_admission_subject_exact_index
    ON research_novelty_admission_subject (evaluation_subject_fingerprint, command_id);

CREATE TRIGGER research_novelty_admission_subject_immutable_trigger
    BEFORE UPDATE OR DELETE OR TRUNCATE ON research_novelty_admission_subject
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_history_immutable();
