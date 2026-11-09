-- 复用已封存输入时保持原生产执行与物理 Segment。旧记录继续表示本次直接接收。
ALTER TABLE market_history_preparation_input
    DROP CONSTRAINT market_history_preparation_input_segment_id_raw_event_id_key,
    ADD COLUMN producer_attempt_id TEXT,
    ADD CONSTRAINT market_history_input_producer_distinct
        CHECK (producer_attempt_id IS NULL OR producer_attempt_id <> attempt_id),
    ADD CONSTRAINT market_history_input_producer_query
        FOREIGN KEY (producer_attempt_id, query_fingerprint)
        REFERENCES market_history_preparation_input(attempt_id, query_fingerprint);

CREATE UNIQUE INDEX market_history_input_received_once
    ON market_history_preparation_input(segment_id, raw_event_id)
    WHERE producer_attempt_id IS NULL;
