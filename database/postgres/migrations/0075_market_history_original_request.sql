-- UUID 归属于原操作；只对新形态生效，禁止一个 UUID 指向另一份请求。
ALTER TABLE market_acquisition_intent
    ADD CONSTRAINT market_history_original_request_uuid_check
    CHECK (identity_version <> 3 OR
        (requested_scope ? 'original_request_id' AND
         jsonb_typeof(requested_scope->'original_request_id') = 'string' AND
         (requested_scope->>'original_request_id') ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'));

CREATE UNIQUE INDEX market_history_original_request_uuid
ON market_acquisition_intent ((requested_scope->>'original_request_id'))
WHERE identity_version = 3;
