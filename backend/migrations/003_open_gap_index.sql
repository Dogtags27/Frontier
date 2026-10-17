CREATE TABLE IF NOT EXISTS open_gap_index (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id text NOT NULL,
    method_family_id text NOT NULL,
    method_family text NOT NULL,
    PRIMARY KEY (user_id, task_id, method_family_id)
);

CREATE INDEX IF NOT EXISTS open_gap_index_cell ON open_gap_index (task_id, method_family);
