CREATE TABLE backtest_worker_presence (
    worker_instance_id UUID PRIMARY KEY CHECK (
        worker_instance_id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    ),
    service_version TEXT NOT NULL CHECK (btrim(service_version) <> ''),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'DRAINING')),
    started_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    CHECK (last_seen_at >= started_at)
);

CREATE INDEX backtest_worker_presence_freshness
    ON backtest_worker_presence (last_seen_at DESC, worker_instance_id ASC);
