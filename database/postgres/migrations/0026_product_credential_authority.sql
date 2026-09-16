CREATE TABLE product_credential (
    credential_id UUID PRIMARY KEY,
    credential_kind TEXT NOT NULL CHECK (credential_kind <> '' AND credential_kind !~ '\s'),
    provider_id TEXT NOT NULL CHECK (provider_id <> '' AND provider_id !~ '\s'),
    ciphertext BYTEA NOT NULL CHECK (octet_length(ciphertext) > 12),
    key_version INTEGER NOT NULL CHECK (key_version = 1),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (credential_kind, provider_id)
);
