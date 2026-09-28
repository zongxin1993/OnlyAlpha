-- Preserve exact bar construction beside immutable segment evidence. Historical
-- NULL rows have no provable construction and are never inferred from capabilities.
ALTER TABLE market_ingest_segment
    ADD COLUMN bar_construction JSONB,
    ADD CONSTRAINT market_ingest_segment_bar_construction_shape_check
        CHECK (bar_construction IS NULL OR data_kind = 'BAR');
