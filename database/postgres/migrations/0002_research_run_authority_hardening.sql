ALTER TABLE research_run
    ADD CONSTRAINT research_run_time_order CHECK (
        (started_at IS NULL OR started_at >= queued_at)
        AND (
            cancel_requested_at IS NULL
            OR (started_at IS NOT NULL AND cancel_requested_at >= started_at)
        )
        AND (
            finished_at IS NULL
            OR (
                finished_at >= queued_at
                AND (started_at IS NULL OR finished_at >= started_at)
                AND (cancel_requested_at IS NULL OR finished_at >= cancel_requested_at)
            )
        )
    ),
    ADD CONSTRAINT research_run_running_has_no_cancel_request CHECK (
        state <> 'RUNNING' OR cancel_requested_at IS NULL
    ),
    ADD CONSTRAINT research_run_execution_required CHECK (
        state NOT IN ('COMPLETED', 'FAILED') OR started_at IS NOT NULL
    ),
    ADD CONSTRAINT research_run_cancelled_lifecycle CHECK (
        state <> 'CANCELLED'
        OR (started_at IS NULL AND cancel_requested_at IS NULL)
        OR (started_at IS NOT NULL AND cancel_requested_at IS NOT NULL)
    ),
    ADD CONSTRAINT research_run_artifact_requires_result CHECK (
        artifact_content_fingerprint IS NULL OR research_result_fingerprint IS NOT NULL
    );
