"""
Guideline-to-license applicability model (app/models/licensing.py)

NOTE (2026-08-12): This file originally also defined a LicenseTypes model
-- removed after discovering RegulatorLicenses (app/models/re.py) already
serves that exact role, already populated with 102 real rows and already
used live in Stage 3 clause post-processing (app/services/
clause_post_processor.py). RegulatorLicenses was extended instead with
the refinements this file's research surfaced as necessary. Only the
guideline-level applicability mapping remains genuinely new -- clause-level
applicability already exists via clauses.applicable_to; this table is the
guideline-wide view GRACE needs for org-to-guideline matching.
"""
from app import db
from sqlalchemy import func


class GuidelineLicenseApplicability(db.Model):
    __tablename__ = "GuidelineLicenseApplicability"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    guideline_id = db.Column(db.BigInteger, db.ForeignKey("guidelines.id"), nullable=False)
    regulator_license_id = db.Column(db.Integer, db.ForeignKey("regulator_licenses.id"), nullable=False)

    # 'llm_extracted' / 'human_confirmed' / 'human_overridden'
    determined_by = db.Column(db.String(50), nullable=False)

    needs_review = db.Column(db.Boolean, nullable=False, default=True)
    reviewed_by_user_id = db.Column(db.BigInteger, db.ForeignKey("Users.id"), nullable=True)
    reviewed_at = db.Column(db.TIMESTAMP, nullable=True)

    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
