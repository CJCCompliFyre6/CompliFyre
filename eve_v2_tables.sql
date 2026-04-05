-- =============================================================
-- EVE v2 Module C — 5 New Tables
-- Database: PostgreSQL
-- Run this directly in your PostgreSQL database
-- Safe: only creates new tables, touches nothing existing
-- =============================================================


-- -------------------------------------------------------------
-- Table 1: guideline_eve_context
-- EVE Step 1 output — context classification per guideline
-- One row per guideline, generated once on Complifyre side
-- -------------------------------------------------------------

CREATE TABLE IF NOT EXISTS guideline_eve_context (
    id                  BIGSERIAL       PRIMARY KEY,
    guideline_id        BIGINT          NOT NULL UNIQUE,
    regulation_type     VARCHAR(50)     NOT NULL,
    -- valid: RBI, SEBI, IRDAI, NABARD, ISO, PCI_DSS, SWIFT, DPDP, GDPR, BASEL, OTHER
    domain              VARCHAR(50)     NOT NULL,
    -- valid: INFOSEC, DATA_PRIVACY, CREDIT_RISK, MARKET_RISK,
    --        OPERATIONAL_RISK, IT_GOVERNANCE, VENDOR_RISK, FINANCIAL_REPORTING
    auditor_profile     VARCHAR(50)     NOT NULL,
    -- valid: INFOSEC_AUDITOR, PRIVACY_AUDITOR, ITGC_AUDITOR, RISK_AUDITOR, FINANCIAL_AUDITOR
    raw_output_json     JSONB           NULL,
    generated_at        TIMESTAMP       NOT NULL DEFAULT NOW(),
    generated_by        BIGINT          NULL,

    CONSTRAINT fk_gec_guideline
        FOREIGN KEY (guideline_id)
        REFERENCES guidelines(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_gec_user
        FOREIGN KEY (generated_by)
        REFERENCES "Users"(id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_gec_guideline_id
    ON guideline_eve_context(guideline_id);


-- -------------------------------------------------------------
-- Table 2: control_checklist
-- EVE Steps 3+4 output — master atomic checklist per control activity
-- One row per control_activity, generated once on Complifyre side
-- -------------------------------------------------------------

CREATE TABLE IF NOT EXISTS control_checklist (
    id                          BIGSERIAL       PRIMARY KEY,
    control_activity_id         INTEGER         NOT NULL UNIQUE,
    dimension_design            BOOLEAN         NOT NULL DEFAULT FALSE,
    dimension_implementation    BOOLEAN         NOT NULL DEFAULT FALSE,
    dimension_operating         BOOLEAN         NOT NULL DEFAULT FALSE,
    checklist_json              JSONB           NOT NULL,
    -- Array of checklist items, each with:
    -- id (CHK_001...), requirement, control_pattern, lifecycle_stage,
    -- effectiveness_type, weight, testing_method, testing_approach,
    -- expected_evidence_types, evidence_logic, requirement_type,
    -- allows_compensating_control, compensating_control_logic,
    -- evaluation_logic {check_for, pass_condition, fail_condition},
    -- failure_impact
    admissibility_rules_json    JSONB           NULL,
    sampling_rules_json         JSONB           NULL,
    scoring_rules_json          JSONB           NULL,
    version                     INTEGER         NOT NULL DEFAULT 1,
    raw_output_json             JSONB           NULL,
    generated_at                TIMESTAMP       NOT NULL DEFAULT NOW(),
    generated_by                BIGINT          NULL,

    CONSTRAINT fk_cc_control_activity
        FOREIGN KEY (control_activity_id)
        REFERENCES control_activities(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_cc_user
        FOREIGN KEY (generated_by)
        REFERENCES "Users"(id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_cc_control_activity_id
    ON control_checklist(control_activity_id);


-- -------------------------------------------------------------
-- Table 3: project_checklist
-- Project-specific copy of master checklist
-- One row per project_control_activity — auditor works against this
-- -------------------------------------------------------------

CREATE TABLE IF NOT EXISTS project_checklist (
    id                              BIGSERIAL       PRIMARY KEY,
    project_control_activity_id     BIGINT          NOT NULL UNIQUE,
    source_checklist_id             BIGINT          NULL,
    dimension_design                BOOLEAN         NOT NULL DEFAULT FALSE,
    dimension_implementation        BOOLEAN         NOT NULL DEFAULT FALSE,
    dimension_operating             BOOLEAN         NOT NULL DEFAULT FALSE,
    checklist_json                  JSONB           NOT NULL,
    admissibility_rules_json        JSONB           NULL,
    sampling_rules_json             JSONB           NULL,
    scoring_rules_json              JSONB           NULL,
    source_version                  INTEGER         NULL,
    status                          VARCHAR(20)     NOT NULL DEFAULT 'pending',
    -- valid: pending, in_progress, completed
    completed_at                    TIMESTAMP       NULL,
    completed_by                    BIGINT          NULL,
    created_at                      TIMESTAMP       NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_pc_project_control_activity
        FOREIGN KEY (project_control_activity_id)
        REFERENCES project_control_activities(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_pc_source_checklist
        FOREIGN KEY (source_checklist_id)
        REFERENCES control_checklist(id)
        ON DELETE SET NULL,

    CONSTRAINT fk_pc_completed_by
        FOREIGN KEY (completed_by)
        REFERENCES "Users"(id)
        ON DELETE SET NULL,

    CONSTRAINT chk_pc_status
        CHECK (status IN ('pending', 'in_progress', 'completed'))
);

CREATE INDEX IF NOT EXISTS ix_pc_pca_id
    ON project_checklist(project_control_activity_id);

CREATE INDEX IF NOT EXISTS ix_pc_status
    ON project_checklist(status);

CREATE INDEX IF NOT EXISTS ix_pc_source_checklist_id
    ON project_checklist(source_checklist_id);


-- -------------------------------------------------------------
-- Table 4: eve_evidence_result
-- EVE Step 5 output — one row per evidence x checklist item
-- Most granular table — full traceability of every signal
-- -------------------------------------------------------------

CREATE TABLE IF NOT EXISTS eve_evidence_result (
    id                          BIGSERIAL       PRIMARY KEY,
    project_checklist_id        BIGINT          NOT NULL,
    evidence_artifact_id        INTEGER         NOT NULL,
    checklist_item_id           VARCHAR(20)     NOT NULL,
    -- e.g. CHK_001, CHK_002 etc

    -- Admissibility (EVE Step 5 Sub-step 3)
    admissibility               VARCHAR(20)     NOT NULL,
    -- valid: ADMISSIBLE, PARTIAL, INADMISSIBLE
    admissibility_reason        TEXT            NULL,

    -- Evidence metadata (EVE Step 5 Sub-step 4)
    evidence_type               VARCHAR(50)     NULL,
    evidence_strength           VARCHAR(20)     NULL,
    -- valid: STRONG, MODERATE, WEAK
    evidence_role               VARCHAR(20)     NULL,
    -- valid: PRIMARY, SUPPORTING

    -- Signal (EVE Step 5 Sub-step 7)
    signal                      VARCHAR(20)     NOT NULL,
    -- valid: SUPPORTS, CONTRADICTS, INSUFFICIENT
    signal_basis                TEXT            NULL,

    -- Item status (EVE Step 5 Sub-step 8)
    item_status                 VARCHAR(10)     NOT NULL,
    -- valid: PASS, PARTIAL, FAIL

    -- Confidence (EVE Step 5 Sub-step 10)
    confidence                  VARCHAR(10)     NULL,
    -- valid: HIGH, MEDIUM, LOW

    -- Exact location within the evidence
    evidence_reference          TEXT            NULL,

    -- Sample testing fields (if applicable)
    sample_applicable           BOOLEAN         NULL,
    sample_size                 INTEGER         NULL,
    population_size             INTEGER         NULL,
    exception_rate              NUMERIC(5,2)    NULL,
    sample_within_audit_period  BOOLEAN         NULL,

    -- Full raw Step 5 JSON for this evidence
    raw_output_json             JSONB           NULL,

    generated_at                TIMESTAMP       NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_eer_project_checklist
        FOREIGN KEY (project_checklist_id)
        REFERENCES project_checklist(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_eer_evidence_artifact
        FOREIGN KEY (evidence_artifact_id)
        REFERENCES project_evidence_artifacts(id)
        ON DELETE CASCADE,

    CONSTRAINT uq_eve_evidence_checklist_item
        UNIQUE (project_checklist_id, evidence_artifact_id, checklist_item_id),

    CONSTRAINT chk_eer_admissibility
        CHECK (admissibility IN ('ADMISSIBLE', 'PARTIAL', 'INADMISSIBLE')),

    CONSTRAINT chk_eer_signal
        CHECK (signal IN ('SUPPORTS', 'CONTRADICTS', 'INSUFFICIENT')),

    CONSTRAINT chk_eer_item_status
        CHECK (item_status IN ('PASS', 'PARTIAL', 'FAIL')),

    CONSTRAINT chk_eer_strength
        CHECK (evidence_strength IN ('STRONG', 'MODERATE', 'WEAK') OR evidence_strength IS NULL)
);

CREATE INDEX IF NOT EXISTS ix_eer_project_checklist_id
    ON eve_evidence_result(project_checklist_id);

CREATE INDEX IF NOT EXISTS ix_eer_evidence_artifact_id
    ON eve_evidence_result(evidence_artifact_id);

CREATE INDEX IF NOT EXISTS ix_eer_checklist_item_id
    ON eve_evidence_result(checklist_item_id);

CREATE INDEX IF NOT EXISTS ix_eer_signal
    ON eve_evidence_result(signal);

CREATE INDEX IF NOT EXISTS ix_eer_admissibility
    ON eve_evidence_result(admissibility);


-- -------------------------------------------------------------
-- Table 5: eve_control_result
-- EVE Steps 6+7+8 output — one row per project_control_activity
-- Replaces scattered fields on ProjectControlActivity
-- and blob-based ConsolidatedFindingsSummary etc
-- -------------------------------------------------------------

CREATE TABLE IF NOT EXISTS eve_control_result (
    id                              BIGSERIAL       PRIMARY KEY,
    project_control_activity_id     BIGINT          NOT NULL UNIQUE,
    project_checklist_id            BIGINT          NULL,

    -- Step 6 outputs
    checklist_summary_json          JSONB           NULL,
    -- Array: [{checklist_id, requirement, final_status, basis, confidence}, ...]

    observations_json               JSONB           NULL,
    -- Array: [{checklist_id, observation_text, status}, ...]

    findings_json                   JSONB           NULL,
    -- Array: [{finding_id, checklist_id, issue, impact, severity,
    --          evidence_reference}, ...]

    -- Step 7 outputs
    recommendations_json            JSONB           NULL,
    -- Array: [{finding_id, recommendation, implementation_steps,
    --          owner, timeline}, ...]

    -- Step 8 outputs
    clause_rollup_json              JSONB           NULL,
    -- Object: {clause_id, clause_status, clause_severity, summary,
    --          observations, findings, recommendations}

    -- Flat summary fields for fast SQL querying (no JSON parsing needed)
    final_status                    VARCHAR(30)     NULL,
    -- valid: COMPLIANT, PARTIALLY_COMPLIANT, NON_COMPLIANT

    final_severity                  VARCHAR(20)     NULL,
    -- valid: CRITICAL, HIGH, MEDIUM, LOW

    findings_count                  INTEGER         NULL DEFAULT 0,
    critical_findings_count         INTEGER         NULL DEFAULT 0,
    high_findings_count             INTEGER         NULL DEFAULT 0,
    checklist_pass_count            INTEGER         NULL DEFAULT 0,
    checklist_partial_count         INTEGER         NULL DEFAULT 0,
    checklist_fail_count            INTEGER         NULL DEFAULT 0,

    -- Step completion tracking
    step6_completed                 BOOLEAN         NOT NULL DEFAULT FALSE,
    step7_completed                 BOOLEAN         NOT NULL DEFAULT FALSE,
    step8_completed                 BOOLEAN         NOT NULL DEFAULT FALSE,

    generated_at                    TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMP       NOT NULL DEFAULT NOW(),
    generated_by                    BIGINT          NULL,

    CONSTRAINT fk_ecr_project_control_activity
        FOREIGN KEY (project_control_activity_id)
        REFERENCES project_control_activities(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_ecr_project_checklist
        FOREIGN KEY (project_checklist_id)
        REFERENCES project_checklist(id)
        ON DELETE SET NULL,

    CONSTRAINT fk_ecr_user
        FOREIGN KEY (generated_by)
        REFERENCES "Users"(id)
        ON DELETE SET NULL,

    CONSTRAINT chk_ecr_final_status
        CHECK (final_status IN (
            'COMPLIANT', 'PARTIALLY_COMPLIANT', 'NON_COMPLIANT'
        ) OR final_status IS NULL),

    CONSTRAINT chk_ecr_final_severity
        CHECK (final_severity IN (
            'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
        ) OR final_severity IS NULL)
);

CREATE INDEX IF NOT EXISTS ix_ecr_pca_id
    ON eve_control_result(project_control_activity_id);

CREATE INDEX IF NOT EXISTS ix_ecr_final_status
    ON eve_control_result(final_status);

CREATE INDEX IF NOT EXISTS ix_ecr_final_severity
    ON eve_control_result(final_severity);

CREATE INDEX IF NOT EXISTS ix_ecr_project_checklist_id
    ON eve_control_result(project_checklist_id);


-- =============================================================
-- Verify all 5 tables were created
-- Run this after the above to confirm
-- =============================================================

SELECT
    table_name,
    (SELECT COUNT(*) FROM information_schema.columns
     WHERE table_name = t.table_name
     AND table_schema = 'public') AS column_count
FROM information_schema.tables t
WHERE table_schema = 'public'
AND table_name IN (
    'guideline_eve_context',
    'control_checklist',
    'project_checklist',
    'eve_evidence_result',
    'eve_control_result'
)
ORDER BY table_name;
