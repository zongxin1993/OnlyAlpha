ALTER TABLE public.sim_account_revision
    ADD CONSTRAINT sim_account_revision_trading_policy_check CHECK ((
        jsonb_typeof(document::jsonb -> 'instruments') = 'array'
        AND jsonb_array_length(document::jsonb -> 'instruments') BETWEEN 1 AND 32
        AND jsonb_typeof(document::jsonb -> 'risk_rules') = 'array'
        AND jsonb_array_length(document::jsonb -> 'risk_rules') BETWEEN 1 AND 64
        AND (document::jsonb -> 'risk_rules') @> '[{"mode":"ENFORCING"}]'::jsonb
    ) IS TRUE);
