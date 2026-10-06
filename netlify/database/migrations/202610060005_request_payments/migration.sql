ALTER TABLE pool_requests ADD COLUMN payment_reference text;
ALTER TABLE pool_requests ADD COLUMN payment_checked_at timestamptz;
CREATE UNIQUE INDEX pool_request_payment_unique ON pool_requests(payment_reference) WHERE payment_reference IS NOT NULL;
