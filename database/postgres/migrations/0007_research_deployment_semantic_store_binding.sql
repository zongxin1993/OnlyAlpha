CREATE TABLE research_deployment_semantic_store_binding (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton = TRUE),
    semantic_store_id UUID NOT NULL,
    bound_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
