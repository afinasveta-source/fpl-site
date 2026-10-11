-- 002 из migrations/versions/002_auth.py (backend face-painting-league)
ALTER TABLE auth_tokens ADD COLUMN target_email text;
ALTER TABLE auth_tokens ADD CONSTRAINT ck_auth_set_password_email
    CHECK (token_type <> 'set_password' OR target_email IS NOT NULL);
CREATE INDEX ix_auth_tokens_user_type ON auth_tokens(user_id, token_type) WHERE used_at IS NULL;
CREATE TABLE auth_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_auth_sessions_user ON auth_sessions(user_id) WHERE revoked_at IS NULL;
CREATE TABLE auth_rate_limits (
    key_hash text PRIMARY KEY,
    window_start timestamptz NOT NULL,
    attempts integer NOT NULL CHECK (attempts > 0)
);
