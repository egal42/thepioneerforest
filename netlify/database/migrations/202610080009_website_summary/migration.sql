-- Separate from partner pools, payment accounting and allocation records.
CREATE TABLE website_summary (
 id text PRIMARY KEY CHECK(id='tpf'),
 revision text NOT NULL,
 document jsonb NOT NULL,
 published_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE website_summary_history (
 revision text PRIMARY KEY,
 document jsonb NOT NULL,
 published_at timestamptz NOT NULL DEFAULT now()
);
