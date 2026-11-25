CREATE TABLE public.sim_run_reservation (
    command_id uuid PRIMARY KEY,
    command_kind text NOT NULL DEFAULT 'START_SIM_RUN' CHECK (command_kind = 'START_SIM_RUN'),
    command_fingerprint text NOT NULL,
    intent text NOT NULL CHECK (encode(sha256(convert_to(intent, 'UTF8')), 'hex') = command_fingerprint),
    deployment_id text NOT NULL CHECK (deployment_id IS NOT DISTINCT FROM (intent::jsonb ->> 'deployment_id')),
    account_id text NOT NULL CHECK (account_id IS NOT DISTINCT FROM (intent::jsonb ->> 'account_id')),
    run_id text NOT NULL DEFAULT gen_random_uuid()::text UNIQUE
        CHECK (run_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
    generation text NOT NULL CHECK (generation ~ '^[0-9a-f]{64}$'),
    kernel_artifact text NOT NULL CHECK (kernel_artifact ~ '^[0-9a-f]{64}$'),
    FOREIGN KEY (command_id, command_kind, command_fingerprint)
        REFERENCES public.product_command_admission (command_id, command_kind, command_fingerprint),
    UNIQUE (command_id, run_id, deployment_id, account_id)
);
CREATE INDEX sim_run_reservation_deployment ON public.sim_run_reservation (deployment_id, command_id);

ALTER TABLE public.product_command_receipt ADD UNIQUE (command_id, outcome_id);
CREATE TABLE public.sim_run_admission (
    command_id uuid PRIMARY KEY,
    run_id text NOT NULL,
    deployment_id text NOT NULL,
    account_id text NOT NULL,
    scope_key text NOT NULL UNIQUE REFERENCES public.trading_fact_stream (scope_key),
    binding_fingerprint text NOT NULL CHECK (binding_fingerprint ~ '^[0-9a-f]{64}$'),
    broker_runtime_fingerprint text NOT NULL CHECK (broker_runtime_fingerprint ~ '^[0-9a-f]{64}$'),
    FOREIGN KEY (command_id, run_id, deployment_id, account_id)
        REFERENCES public.sim_run_reservation (command_id, run_id, deployment_id, account_id),
    CONSTRAINT sim_run_admission_receipt_fk FOREIGN KEY (command_id, run_id)
        REFERENCES public.product_command_receipt (command_id, outcome_id),
    -- 每个新流以开户资金初始化。证明跨 Run 账户接续前，同一账户只能建立一个流。
    UNIQUE (deployment_id, account_id)
);

CREATE FUNCTION public.sim_run_require_reservation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.sim_run_reservation WHERE command_id = NEW.command_id) THEN
        RAISE EXCEPTION 'SIM_RUN_RESERVATION_MISSING' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
REVOKE ALL ON FUNCTION public.sim_run_require_reservation() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER sim_run_command_reserved AFTER INSERT ON public.product_command_admission
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.command_kind = 'START_SIM_RUN')
    EXECUTE FUNCTION public.sim_run_require_reservation();

CREATE FUNCTION public.sim_run_require_admission() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.sim_run_admission
        WHERE command_id = NEW.command_id AND run_id = NEW.outcome_id) THEN
        RAISE EXCEPTION 'SIM_RUN_ADMISSION_MISSING' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
REVOKE ALL ON FUNCTION public.sim_run_require_admission() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER sim_run_receipt_admitted AFTER INSERT ON public.product_command_receipt
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.command_kind = 'START_SIM_RUN')
    EXECUTE FUNCTION public.sim_run_require_admission();

CREATE TRIGGER sim_run_reservation_guard BEFORE INSERT ON public.sim_run_reservation
    FOR EACH STATEMENT EXECUTE FUNCTION public.trading_fact_guard_insert();
CREATE TRIGGER sim_run_reservation_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON public.sim_run_reservation
    FOR EACH STATEMENT EXECUTE FUNCTION public.job_content_immutable();
CREATE TRIGGER sim_run_admission_guard BEFORE INSERT ON public.sim_run_admission
    FOR EACH STATEMENT EXECUTE FUNCTION public.trading_fact_guard_insert();
CREATE TRIGGER sim_run_admission_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON public.sim_run_admission
    FOR EACH STATEMENT EXECUTE FUNCTION public.job_content_immutable();

REVOKE ALL ON public.sim_run_reservation, public.sim_run_admission FROM PUBLIC;
GRANT SELECT ON public.sim_run_reservation, public.sim_run_admission TO onlyalpha_node_control;
GRANT INSERT (command_id, command_fingerprint, intent, deployment_id, account_id, generation, kernel_artifact)
    ON public.sim_run_reservation TO onlyalpha_node_control;
GRANT INSERT (command_id, run_id, deployment_id, account_id, scope_key, binding_fingerprint, broker_runtime_fingerprint)
    ON public.sim_run_admission TO onlyalpha_node_control;
