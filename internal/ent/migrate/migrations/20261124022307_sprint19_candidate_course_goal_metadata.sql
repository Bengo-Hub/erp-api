-- Modify "candidates" table
ALTER TABLE "candidates" ADD COLUMN "metadata" jsonb NULL;
-- Modify "goals" table
ALTER TABLE "goals" ADD COLUMN "metadata" jsonb NULL;
-- Modify "training_courses" table
ALTER TABLE "training_courses" ADD COLUMN "metadata" jsonb NULL;
