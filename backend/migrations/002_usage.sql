CREATE TABLE IF NOT EXISTS llm_usage (
    id uuid PRIMARY KEY,
    user_id uuid,
    org_id uuid,
    kind text NOT NULL CHECK (kind IN ('chat', 'embed')),
    model text NOT NULL,
    input_tokens integer NOT NULL,
    output_tokens integer NOT NULL,
    usd numeric(14, 6) NOT NULL,
    cached boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS llm_usage_user_created ON llm_usage (user_id, created_at);
CREATE INDEX IF NOT EXISTS llm_usage_org_created ON llm_usage (org_id, created_at);
CREATE INDEX IF NOT EXISTS llm_usage_created ON llm_usage (created_at);

CREATE TABLE IF NOT EXISTS rate_buckets (
    key text PRIMARY KEY,
    tokens double precision NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rate_concurrency (
    key text PRIMARY KEY,
    held integer NOT NULL
);
