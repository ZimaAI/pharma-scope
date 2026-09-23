-- Durable aggregate checkpoint used by the API until all domain tables are
-- migrated.  It is safe to run repeatedly (CREATE IF NOT EXISTS).
CREATE TABLE IF NOT EXISTS pharmascope_state_checkpoint (
  id integer PRIMARY KEY,
  schema_version integer NOT NULL,
  payload jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_pharmascope_state_checkpoint_updated_at
  ON pharmascope_state_checkpoint (updated_at);
