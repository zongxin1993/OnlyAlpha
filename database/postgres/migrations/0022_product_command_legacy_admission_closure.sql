CREATE TEMPORARY TABLE product_command_legacy_binding_closure
ON COMMIT DROP
AS
SELECT
    command_id,
    command_kind,
    command_fingerprint,
    schema_version,
    'product_command_receipt'::TEXT AS source
FROM product_command_receipt

UNION ALL

SELECT
    command_id,
    'FREEZE_STRATEGY'::TEXT,
    command_fingerprint,
    1::SMALLINT,
    'strategy_freeze_command_admission'::TEXT
FROM strategy_freeze_command_admission

UNION ALL

SELECT
    command_id,
    'EVALUATE_QUALIFICATION'::TEXT,
    command_fingerprint,
    1::SMALLINT,
    'qualification_command_admission'::TEXT
FROM qualification_command_admission

UNION ALL

SELECT
    command_id,
    command_kind,
    command_fingerprint,
    schema_version,
    'product_command_admission'::TEXT
FROM product_command_admission;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM product_command_legacy_binding_closure
        WHERE schema_version <> 1
           OR command_fingerprint !~ '^[0-9a-f]{64}$'
           OR command_kind NOT IN (
                'CREATE_RESEARCH_RUN',
                'CANCEL_RESEARCH_RUN',
                'FREEZE_STRATEGY',
                'PROMOTE_STRATEGY',
                'CREATE_BACKTEST_RUN',
                'CANCEL_BACKTEST_RUN',
                'EVALUATE_QUALIFICATION',
                'CREATE_SYMBOLIC_SEARCH_EXPERIMENT',
                'CREATE_PARAMETER_SEARCH_EXPERIMENT',
                'ADVANCE_SEARCH_EXPERIMENT'
           )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = 'check_violation',
            MESSAGE = 'Product Command legacy Admission source is invalid';
    END IF;

    IF EXISTS (
        SELECT command_id
        FROM product_command_legacy_binding_closure
        GROUP BY command_id
        HAVING count(DISTINCT (command_kind, command_fingerprint)) <> 1
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = 'check_violation',
            MESSAGE = 'Product Command legacy Admission conflict';
    END IF;
END
$$;

INSERT INTO product_command_admission (
    command_id,
    command_kind,
    command_fingerprint,
    schema_version
)
SELECT DISTINCT
    legacy.command_id,
    legacy.command_kind,
    legacy.command_fingerprint,
    1
FROM product_command_legacy_binding_closure AS legacy
WHERE legacy.source <> 'product_command_admission'
  AND NOT EXISTS (
      SELECT 1
      FROM product_command_admission AS admission
      WHERE admission.command_id = legacy.command_id
  )
ORDER BY legacy.command_id;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM product_command_legacy_binding_closure AS legacy
        LEFT JOIN product_command_admission AS admission
          ON admission.command_id = legacy.command_id
         AND admission.command_kind = legacy.command_kind
         AND admission.command_fingerprint = legacy.command_fingerprint
         AND admission.schema_version = legacy.schema_version
        WHERE legacy.source <> 'product_command_admission'
          AND admission.command_id IS NULL
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = 'check_violation',
            MESSAGE = 'Product Command legacy Admission post-verification failed';
    END IF;
END
$$;
