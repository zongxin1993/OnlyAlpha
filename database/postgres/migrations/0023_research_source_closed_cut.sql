-- Source-owned Research operational history. Migration DDL locks writers while
-- baseline observations are installed. Earlier mutable revisions are not invented.
CREATE TABLE research_source_history_frontier (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    last_index BIGINT NOT NULL CHECK (last_index >= 0)
);
INSERT INTO research_source_history_frontier (singleton, last_index) VALUES (TRUE, 0);

CREATE TABLE research_source_history (
    event_index BIGINT PRIMARY KEY CHECK (event_index > 0),
    source_family TEXT NOT NULL CHECK (source_family IN (
        'RESEARCH_RUN', 'RESEARCH_ATTEMPT', 'PRODUCT_COMMAND_ADMISSION', 'PRODUCT_COMMAND_RECEIPT'
    )),
    native_locator TEXT NOT NULL,
    source_row JSONB NOT NULL CHECK (jsonb_typeof(source_row) = 'object'),
    operation TEXT NOT NULL CHECK (operation IN ('BASELINE', 'INSERT', 'UPDATE')),
    schema_version SMALLINT NOT NULL DEFAULT 1 CHECK (schema_version = 1)
);
CREATE INDEX research_source_history_family_index
    ON research_source_history (source_family, event_index);

CREATE TABLE research_source_closed_cut (
    cut_fingerprint TEXT PRIMARY KEY CHECK (cut_fingerprint ~ '^[0-9a-f]{64}$'),
    source_family TEXT NOT NULL CHECK (source_family IN (
        'RESEARCH_RUN', 'RESEARCH_ATTEMPT', 'PRODUCT_COMMAND_ADMISSION', 'PRODUCT_COMMAND_RECEIPT'
    )),
    frontier BIGINT NOT NULL CHECK (frontier >= 0),
    canonical_document TEXT NOT NULL,
    schema_version SMALLINT NOT NULL CHECK (schema_version = 1)
);

CREATE FUNCTION research_source_history_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Research source history and cuts are immutable';
END
$$;
CREATE TRIGGER research_source_history_immutable_trigger
    BEFORE UPDATE OR DELETE OR TRUNCATE ON research_source_history
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_history_immutable();
CREATE TRIGGER research_source_closed_cut_immutable_trigger
    BEFORE UPDATE OR DELETE OR TRUNCATE ON research_source_closed_cut
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_history_immutable();

CREATE FUNCTION research_source_record(
    p_family TEXT, p_locator TEXT, p_row JSONB, p_operation TEXT
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_index BIGINT;
BEGIN
    UPDATE research_source_history_frontier SET last_index = last_index + 1
    WHERE singleton = TRUE RETURNING last_index INTO v_index;
    IF v_index IS NULL THEN
        RAISE EXCEPTION 'Research source history frontier missing';
    END IF;
    INSERT INTO research_source_history (
        event_index, source_family, native_locator, source_row, operation
    ) VALUES (v_index, p_family, p_locator, p_row, p_operation);
END
$$;

-- The migration is one transaction. Baseline order is explicit and reproducible;
-- it asserts only the currently retained revision of each legacy mutable row.
-- Lock before enumerating, so a concurrent writer cannot commit between the
-- baseline scan and installation of the capturing triggers.
LOCK TABLE research_run, research_run_attempt, product_command_admission,
    product_command_receipt IN SHARE ROW EXCLUSIVE MODE;
DO $$ DECLARE v_row RECORD; BEGIN
    FOR v_row IN SELECT * FROM research_run ORDER BY run_id LOOP
        PERFORM research_source_record('RESEARCH_RUN', v_row.run_id::text, to_jsonb(v_row), 'BASELINE');
    END LOOP;
    FOR v_row IN SELECT * FROM research_run_attempt ORDER BY run_id, attempt_number, attempt_id LOOP
        PERFORM research_source_record('RESEARCH_ATTEMPT', v_row.attempt_id::text, to_jsonb(v_row), 'BASELINE');
    END LOOP;
    FOR v_row IN SELECT * FROM product_command_admission ORDER BY command_id LOOP
        PERFORM research_source_record('PRODUCT_COMMAND_ADMISSION', v_row.command_id::text, to_jsonb(v_row), 'BASELINE');
    END LOOP;
    FOR v_row IN SELECT * FROM product_command_receipt ORDER BY command_id LOOP
        PERFORM research_source_record('PRODUCT_COMMAND_RECEIPT', v_row.command_id::text, to_jsonb(v_row), 'BASELINE');
    END LOOP;
END $$;

CREATE FUNCTION research_source_capture_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_locator TEXT;
BEGIN
    IF TG_TABLE_NAME = 'research_run' THEN
        v_locator := NEW.run_id::text;
    ELSIF TG_TABLE_NAME = 'research_run_attempt' THEN
        v_locator := NEW.attempt_id::text;
    ELSE
        v_locator := NEW.command_id::text;
    END IF;
    PERFORM research_source_record(TG_ARGV[0], v_locator, to_jsonb(NEW), TG_OP);
    RETURN NEW;
END
$$;

CREATE TRIGGER research_run_source_history
    AFTER INSERT OR UPDATE ON research_run
    FOR EACH ROW EXECUTE FUNCTION research_source_capture_change('RESEARCH_RUN');
CREATE TRIGGER research_attempt_source_history
    AFTER INSERT OR UPDATE ON research_run_attempt
    FOR EACH ROW EXECUTE FUNCTION research_source_capture_change('RESEARCH_ATTEMPT');
CREATE TRIGGER product_admission_source_history
    AFTER INSERT OR UPDATE ON product_command_admission
    FOR EACH ROW EXECUTE FUNCTION research_source_capture_change('PRODUCT_COMMAND_ADMISSION');
CREATE TRIGGER product_receipt_source_history
    AFTER INSERT OR UPDATE ON product_command_receipt
    FOR EACH ROW EXECUTE FUNCTION research_source_capture_change('PRODUCT_COMMAND_RECEIPT');

-- Deleting source rows would make the published historical chain unverifiable.
CREATE FUNCTION research_source_delete_forbidden() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Research operational source facts cannot be deleted';
END
$$;
CREATE TRIGGER research_run_source_no_delete
    BEFORE DELETE OR TRUNCATE ON research_run
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_delete_forbidden();
CREATE TRIGGER research_attempt_source_no_delete
    BEFORE DELETE OR TRUNCATE ON research_run_attempt
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_delete_forbidden();
CREATE TRIGGER product_admission_source_no_delete
    BEFORE DELETE OR TRUNCATE ON product_command_admission
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_delete_forbidden();
CREATE TRIGGER product_receipt_source_no_delete
    BEFORE DELETE OR TRUNCATE ON product_command_receipt
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_delete_forbidden();
