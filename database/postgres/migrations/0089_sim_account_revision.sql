CREATE TABLE public.sim_account_revision (
    revision_fingerprint text PRIMARY KEY,
    document text NOT NULL,
    deployment_id uuid GENERATED ALWAYS AS ((document::jsonb ->> 'deployment_id')::uuid) STORED NOT NULL
        REFERENCES public.research_deployment_semantic_store_binding (semantic_store_id),
    account_id text GENERATED ALWAYS AS (document::jsonb ->> 'account_id') STORED NOT NULL
        CHECK (length(account_id) BETWEEN 1 AND 128),
    broker_integration_id uuid GENERATED ALWAYS AS ((document::jsonb ->> 'broker_integration_id')::uuid) STORED NOT NULL
        REFERENCES public.integration (integration_id),
    CHECK (revision_fingerprint = encode(sha256(convert_to(document, 'UTF8')), 'hex')),
    CHECK ((document::jsonb -> 'schema_version' = '1'::jsonb
        AND jsonb_typeof(document::jsonb -> 'opening_cash') = 'object') IS TRUE),
    UNIQUE (deployment_id, account_id, revision_fingerprint)
);

CREATE TRIGGER sim_account_revision_guard BEFORE INSERT ON public.sim_account_revision
    FOR EACH STATEMENT EXECUTE FUNCTION public.trading_fact_guard_insert();
CREATE TRIGGER sim_account_revision_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON public.sim_account_revision
    FOR EACH STATEMENT EXECUTE FUNCTION public.job_content_immutable();

REVOKE ALL ON public.sim_account_revision FROM PUBLIC;
GRANT SELECT, INSERT (revision_fingerprint, document) ON public.sim_account_revision TO onlyalpha_node_control;
