ALTER TABLE product_command_admission
    DROP CONSTRAINT product_command_admission_command_kind_check;
ALTER TABLE product_command_admission
    ADD CONSTRAINT product_command_admission_command_kind_check CHECK (
        command_kind IN (
            'CREATE_RESEARCH_RUN',
            'CANCEL_RESEARCH_RUN',
            'FREEZE_STRATEGY',
            'PROMOTE_STRATEGY',
            'CREATE_BACKTEST_RUN',
            'CANCEL_BACKTEST_RUN',
            'EVALUATE_QUALIFICATION',
            'CREATE_SYMBOLIC_SEARCH_EXPERIMENT',
            'CREATE_PARAMETER_SEARCH_EXPERIMENT',
            'ADVANCE_SEARCH_EXPERIMENT',
            'CREATE_INTEGRATION',
            'UPDATE_INTEGRATION_DRAFT',
            'SET_INTEGRATION_SECRET',
            'CLEAR_INTEGRATION_SECRET',
            'RESET_INTEGRATION_DRAFT_CONTRACT',
            'PUBLISH_INTEGRATION_REVISION',
            'SET_INTEGRATION_LIFECYCLE'
        )
    );

ALTER TABLE product_command_receipt
    DROP CONSTRAINT product_command_receipt_command_kind_check;
ALTER TABLE product_command_receipt
    ADD CONSTRAINT product_command_receipt_command_kind_check CHECK (
        command_kind IN (
            'CREATE_RESEARCH_RUN',
            'CANCEL_RESEARCH_RUN',
            'FREEZE_STRATEGY',
            'PROMOTE_STRATEGY',
            'CREATE_BACKTEST_RUN',
            'CANCEL_BACKTEST_RUN',
            'EVALUATE_QUALIFICATION',
            'CREATE_SYMBOLIC_SEARCH_EXPERIMENT',
            'CREATE_PARAMETER_SEARCH_EXPERIMENT',
            'ADVANCE_SEARCH_EXPERIMENT',
            'CREATE_INTEGRATION',
            'UPDATE_INTEGRATION_DRAFT',
            'SET_INTEGRATION_SECRET',
            'CLEAR_INTEGRATION_SECRET',
            'RESET_INTEGRATION_DRAFT_CONTRACT',
            'PUBLISH_INTEGRATION_REVISION',
            'SET_INTEGRATION_LIFECYCLE'
        )
    );

ALTER TABLE product_command_receipt
    DROP CONSTRAINT product_command_receipt_outcome_kind_check;
ALTER TABLE product_command_receipt
    ADD CONSTRAINT product_command_receipt_outcome_kind_check CHECK (
        outcome_kind IN (
            'RESEARCH_RUN',
            'STRATEGY',
            'STRATEGY_PROMOTION',
            'BACKTEST_RUN',
            'QUALIFICATION_DECISION',
            'SEARCH_EXPERIMENT',
            'INTEGRATION',
            'INTEGRATION_REVISION'
        )
    );

ALTER TABLE product_command_receipt
    DROP CONSTRAINT product_command_receipt_outcome_id_check;
ALTER TABLE product_command_receipt
    ADD CONSTRAINT product_command_receipt_outcome_id_check CHECK (
        (
            outcome_kind IN ('RESEARCH_RUN', 'BACKTEST_RUN', 'INTEGRATION')
            AND outcome_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
        )
        OR
        (
            outcome_kind IN (
                'STRATEGY',
                'STRATEGY_PROMOTION',
                'QUALIFICATION_DECISION',
                'SEARCH_EXPERIMENT',
                'INTEGRATION_REVISION'
            )
            AND outcome_id ~ '^[0-9a-f]{64}$'
        )
    );
