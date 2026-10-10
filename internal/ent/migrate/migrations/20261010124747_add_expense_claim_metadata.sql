-- Claim provenance for claims raised by other services (logistics per diem for staff drivers).
-- Nullable, so adding it to the populated table is safe online.
ALTER TABLE "expense_claims" ADD COLUMN IF NOT EXISTS "metadata" jsonb NULL;
-- GIN for the source_key containment lookup that makes external claims idempotent.
CREATE INDEX IF NOT EXISTS "expenseclaim_metadata" ON "expense_claims" USING gin ("metadata");
