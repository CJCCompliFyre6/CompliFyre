-- Status tracking for the "Check for new guidelines" feature (item #133).
-- Captures not just success/fail but the SPECIFIC reason, per Ankita's
-- explicit request to see why a check failed, not just that it did --
-- needed to actually analyse patterns across regulators and find
-- workarounds for the ones that get blocked.

ALTER TABLE "RegulatoryBodies" ADD COLUMN IF NOT EXISTS last_check_status VARCHAR(50) NOT NULL DEFAULT 'NEVER_CHECKED';
ALTER TABLE "RegulatoryBodies" ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMP;
ALTER TABLE "RegulatoryBodies" ADD COLUMN IF NOT EXISTS last_check_notes TEXT;

CREATE INDEX IF NOT EXISTS idx_regulatory_bodies_check_status ON "RegulatoryBodies"(last_check_status);
