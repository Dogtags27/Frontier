CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY,
    email text NOT NULL UNIQUE,
    signup_role text NOT NULL CHECK (signup_role IN ('student', 'supervisor')),
    role text NOT NULL CHECK (role IN ('student', 'supervisor', 'admin')),
    display_name text NOT NULL DEFAULT '',
    org_id uuid,
    graph_name text,
    graph_status text NOT NULL DEFAULT 'pending' CHECK (graph_status IN ('pending', 'ready')),
    created_at timestamptz NOT NULL DEFAULT now(),
    disabled boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS orgs (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    owner_supervisor_id uuid NOT NULL REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS enrollments (
    supervisor_id uuid NOT NULL REFERENCES users (id),
    student_id uuid NOT NULL REFERENCES users (id),
    org_id uuid NOT NULL REFERENCES orgs (id),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'removed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (supervisor_id, student_id)
);

CREATE TABLE IF NOT EXISTS invites (
    id uuid PRIMARY KEY,
    code_hash text NOT NULL,
    code text NOT NULL,
    org_id uuid NOT NULL REFERENCES orgs (id),
    created_by uuid NOT NULL REFERENCES users (id),
    expires_at timestamptz NOT NULL,
    max_uses integer NOT NULL,
    used integer NOT NULL DEFAULT 0,
    revoked boolean NOT NULL DEFAULT false
);

CREATE UNIQUE INDEX IF NOT EXISTS invites_one_live
    ON invites (org_id) WHERE revoked = false;
