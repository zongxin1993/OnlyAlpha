-- Precondition: checksummed history through 0048; operator has CREATEROLE and owns
-- this schema. Roles are cluster-scoped NOLOGIN privilege groups, never passwords.
-- DDL/ACL/role creation and ledger insert commit in the same transaction. Failure
-- rolls all changes back; exact existing role shape is revalidated on fresh-schema
-- installation. No existing fact or published SQL is rewritten.
-- Runtime actors are not schema owners/superusers. Privileged administration can
-- disable guards and is outside the runtime bypass threat model.
DO $$
DECLARE
    role_name TEXT;
    role_oid OID;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['onlyalpha_chart_input_reader', 'onlyalpha_chart_execution_controller'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT', role_name);
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_roles
            WHERE rolname = role_name AND NOT rolcanlogin AND NOT rolsuper
              AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication
              AND NOT rolbypassrls AND rolinherit AND rolconnlimit = -1
        ) OR EXISTS (
            -- The group may have deployment login members, but it cannot itself
            -- inherit another role or escalate via SET ROLE / ADMIN membership.
            SELECT 1 FROM pg_catalog.pg_auth_members m
            JOIN pg_catalog.pg_roles r ON r.oid = m.member WHERE r.rolname = role_name
        ) THEN
            RAISE EXCEPTION 'CHART_NATIVE_DATABASE_ROLE_UNSAFE';
        END IF;
        SELECT oid INTO role_oid FROM pg_catalog.pg_roles WHERE rolname = role_name;
        -- A preexisting privilege group is acceptable only when it has no
        -- authority in this database yet. Do not silently sanitize/adopt an
        -- unrelated role with extra grants or owned objects.
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_class c WHERE c.relowner = role_oid
                   OR EXISTS (SELECT 1 FROM pg_catalog.aclexplode(c.relacl) a WHERE a.grantee = role_oid))
           OR EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n WHERE n.nspowner = role_oid
                      OR EXISTS (SELECT 1 FROM pg_catalog.aclexplode(n.nspacl) a WHERE a.grantee = role_oid))
           OR EXISTS (SELECT 1 FROM pg_catalog.pg_proc p WHERE p.proowner = role_oid
                      OR EXISTS (SELECT 1 FROM pg_catalog.aclexplode(p.proacl) a WHERE a.grantee = role_oid))
           OR EXISTS (SELECT 1 FROM pg_catalog.pg_default_acl d WHERE d.defaclrole = role_oid
                      OR EXISTS (SELECT 1 FROM pg_catalog.aclexplode(d.defaclacl) a WHERE a.grantee = role_oid))
           OR EXISTS (SELECT 1 FROM pg_catalog.pg_attribute c
                      CROSS JOIN LATERAL pg_catalog.aclexplode(c.attacl) a WHERE a.grantee = role_oid)
           OR EXISTS (SELECT 1 FROM pg_catalog.pg_database d WHERE d.datname = current_database()
                      AND (d.datdba = role_oid OR EXISTS (
                          SELECT 1 FROM pg_catalog.aclexplode(d.datacl) a WHERE a.grantee = role_oid))) THEN
            RAISE EXCEPTION 'CHART_NATIVE_DATABASE_ROLE_UNSAFE';
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM public.research_run_attempt a
               JOIN public.research_run r USING (run_id) WHERE r.origin_kind = 'CHART_CALCULATION') THEN
        RAISE EXCEPTION 'CHART_NATIVE_EXISTING_ATTEMPT_UNSUPPORTED';
    END IF;
END;
$$;

GRANT USAGE ON SCHEMA public TO onlyalpha_chart_input_reader;
GRANT SELECT ON
    onlyalpha_schema_migration,
    product_command_admission, product_command_receipt,
    chart_calculation_operation, chart_calculation_preparation_fact,
    chart_calculation_compilation, chart_calculation_run_admission,
    research_run, research_run_id_reservation, research_run_attempt,
    integration, integration_revision, integration_revision_secret_binding,
    market_source, market_capture_session, market_ingest_segment,
    market_segment_state_event, market_segment_physical_proof,
    market_coverage_manifest, market_coverage_manifest_segment,
    market_data_revision, market_revision_segment, market_revision_seal
TO onlyalpha_chart_input_reader;
-- Revision secret bindings contain immutable credential references needed by the
-- owning Revision parser, NOT credential plaintext/ciphertext. No credential,
-- Integration Draft, current/latest selector or acquisition write permission.
-- The controller group intentionally has no business writes or entry functions.
-- A separately verified execution consumer must precede any permission to Claim.

CREATE FUNCTION chart_native_publication_attempt_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.research_run
               WHERE run_id = NEW.run_id AND origin_kind = 'CHART_CALCULATION') THEN
        RAISE EXCEPTION 'CHART_NATIVE_EXECUTION_NOT_ENABLED';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION chart_native_publication_attempt_guard() FROM PUBLIC;
-- No role, including the controller group, can start a Chart Attempt while the
-- controlled native host and full terminal/recovery consumers are absent.
CREATE TRIGGER chart_native_publication_attempt_closed
    BEFORE INSERT OR UPDATE ON research_run_attempt
    FOR EACH ROW EXECUTE FUNCTION chart_native_publication_attempt_guard();

-- Rollback/compatibility: do not DROP roles or guards under running consumers.
-- Retain readers/history, disable new writers, then restore a verified snapshot
-- or forward-fix. Previous 0048 Run state CHECK remains unchanged and closed;
-- old schema verifiers correctly report AHEAD until code/reference rollout.
