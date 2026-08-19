-- REVISED after discovering RegulatoryBodies and RegulatoryDocuments
-- already exist (app/models/re.py) but are completely dormant: 0 rows,
-- zero references anywhere in routes/ or services/. Per Rule 15, extending
-- these existing (empty, unused, so zero-risk) tables instead of creating
-- parallel new ones with overlapping purpose.
--
-- RegulatoryBodies already has: name, description, website_url,
-- created_at, updated_at -- covers item #134's "regulator name" and
-- "link" needs directly. Adding geography/industry/governed_institutions.
--
-- RegulatoryDocuments already has: title (= guideline_name), body_id
-- (FK to RegulatoryBodies = regulator link), source_url, document_path,
-- created_at (= discovered_at), status (active/archived/superseded --
-- a DIFFERENT concept from pipeline status, left untouched). Adding
-- file_hash, guideline_id (FK to the real `guidelines` table once
-- ingested), and pipeline_status as a NEW separate column.
--
-- Only genuinely new table: per-transition status history, since neither
-- existing table has anything like that.

ALTER TABLE "RegulatoryBodies" ADD COLUMN IF NOT EXISTS geography VARCHAR(255);
ALTER TABLE "RegulatoryBodies" ADD COLUMN IF NOT EXISTS industry VARCHAR(255);
ALTER TABLE "RegulatoryBodies" ADD COLUMN IF NOT EXISTS governed_institutions TEXT;

ALTER TABLE "RegulatoryDocuments" ADD COLUMN IF NOT EXISTS file_hash VARCHAR(64);
ALTER TABLE "RegulatoryDocuments" ADD COLUMN IF NOT EXISTS guideline_id BIGINT REFERENCES guidelines(id) ON DELETE SET NULL;
ALTER TABLE "RegulatoryDocuments" ADD COLUMN IF NOT EXISTS pipeline_status VARCHAR(50) NOT NULL DEFAULT 'PENDING_DOWNLOAD';

-- Prevent duplicate tracking entries for the same regulator+title combo.
-- Safe to add now (table has 0 rows, so no existing-duplicate conflict).
ALTER TABLE "RegulatoryDocuments" ADD CONSTRAINT uq_body_title UNIQUE (body_id, title);

CREATE INDEX IF NOT EXISTS idx_regulatory_documents_pipeline_status ON "RegulatoryDocuments"(pipeline_status);
CREATE INDEX IF NOT EXISTS idx_regulatory_documents_file_hash ON "RegulatoryDocuments"(file_hash);

CREATE TABLE IF NOT EXISTS regulatory_document_status_history (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES "RegulatoryDocuments"(document_id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL,
    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_status_history_document ON regulatory_document_status_history(document_id);
