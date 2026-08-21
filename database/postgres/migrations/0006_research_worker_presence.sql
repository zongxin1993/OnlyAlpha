CREATE TABLE research_worker_presence (
    worker_instance_id UUID PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    service_version TEXT NOT NULL CHECK (service_version <> ''),
    draining_since TIMESTAMPTZ,
    CONSTRAINT research_worker_presence_time_order CHECK (
        last_seen_at >= started_at
        AND (draining_since IS NULL OR draining_since >= started_at)
    )
);

CREATE INDEX research_worker_presence_freshness
    ON research_worker_presence (last_seen_at DESC, worker_instance_id ASC);
