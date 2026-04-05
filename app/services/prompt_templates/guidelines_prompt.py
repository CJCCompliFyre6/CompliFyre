from pydantic import BaseModel, Field
from datetime import date
from app.models.ai import *


# Import your Pydantic classes from the previous response
# Assuming your classes are in a file named 'regulatory_models.py'
# from regulatory_models import RegulatoryDocument, DocumentDetails, ...
# For this example, I'll include them directly for completeness:

class DocumentDetails(BaseModel):
    DocumentName: str = Field(..., description="Full name of the document or guideline as mentioned on first page")
    IssuingAuthority: str = Field(..., description="Regulator name and country")
    ApplicableIndustries: list[str] = Field(..., description="Industries it applies to (e.g., Banking, NBFCs, fintechs, corporates, government entities)")
    ApplicableOrganizations: list[str] = Field(..., description="Categories of organizations it applies to (e.g., banks, NBFCs, fintechs, corporates, government entities)")
    ApplicableGeography: list[str] = Field(..., description="National or international applicability (only return the name of the country or region)")
    PurposeAndIntent: str = Field(..., description="Purpose and intent of the guideline")
    IssuanceDate: date = Field(..., description="Date of issuance (YYYY-MM-DD format)")
    ComplianceDeadline: date | None = Field(None, description="Effective compliance deadline (YYYY-MM-DD format)")

class RegulatoryAndComplianceAspects(BaseModel):
    LegalStatus: str = Field(..., description="Legally binding or best practice recommendation")
    NonComplianceConsequences: str = Field(..., description="Penalties, enforcement actions, reputational risks")
    RelationToPreviousRegulations: str = Field(..., description="Whether it replaces, updates, or supplements any previous regulations")

class StakeholdersAndApplicability(BaseModel):
    ScopeOfApplicability: str = Field(..., description="Financial institutions, tech firms, government agencies, etc.")
    ImpactOnThirdParties: str = Field(..., description="Impact on third-party service providers, outsourcing firms, and other stakeholders")

class ImplementationAndOversight(BaseModel):
    ComplianceRequirements: str = Field(..., description="Reporting, self-assessments, audits")
    ImplementationTimeline: None | str = Field(None, description="Phased implementation timeline, if applicable")
    GuidanceAvailability: str = Field(..., description="Templates, FAQs, or official guidance for implementation")
    OverseeingBody: str = Field(..., description="Designated regulatory body or department overseeing compliance")
    ResponsibleOfficerRequirement: str = Field(..., description="Whether organizations must appoint a responsible officer (e.g., CISO, Compliance Head)")

class RelatedRegulations(BaseModel):
    OverlappingRegulations: str = Field(..., description="Other regulations issued by the same regulator")
    RelatedNationalRegulations: str = Field(..., description="Related regulations from other national regulators")
    ComparableInternationalStandards: str = Field(..., description="Basel, ISO 27001, NIST, GDPR, FATF, COSO, etc.")

class ComparisonAndIndustryImpact(BaseModel):
    AlignmentWithGlobalPractices: str = Field(..., description="How this guideline aligns with global best practices")
    JurisdictionalDifferences: str = Field(..., description="Differences from similar regulations in other jurisdictions (e.g., US, EU, UK, Singapore)")
    ComplianceChallenges: str = Field(..., description="Potential compliance challenges for affected organizations")
    ImpactOnBusinessOperations: str = Field(..., description="Expected impact on business operations, risk management, and governance practices")

class TypeOfOrgnization(BaseModel):
    Category: str = Field(..., description="Category of orginization eg, Banking, non-banking etc")
    OrgType : str = Field(..., description="Name of type of orginization")
    
class RegulatoryDocument(BaseModel):
    """
    Root schema for a comprehensive regulatory document.
    """
    DocumentDetails: DocumentDetails
    RegulatoryAndComplianceAspects: RegulatoryAndComplianceAspects
    StakeholdersAndApplicability: StakeholdersAndApplicability
    ImplementationAndOversight: ImplementationAndOversight
    RelatedRegulations: RelatedRegulations
    ComparisonAndIndustryImpact: ComparisonAndIndustryImpact
    industries: list[str]= Field(..., description="List of industries the document applies to")
    type_of_organization: TypeOfOrgnization


def guideline_prompt_def():
    """
    Build the guideline prompt using chain-of-thought prompting for page-by-page scanning.
    Returns: a single string to send to the LLM.
    """
    user_guideline = ""
    guideline = AIPrompts.query.filter_by(
        prompt_type="GUIDELINES", is_active=True
    ).first()
    if guideline and guideline.prompt_text:
        user_guideline = guideline.prompt_text

    guideline_prompt = f"""
        ### **Please provide a detailed analysis of the selected regulatory circular or guideline.**

        ### Your final output must contain only the JSON object, formatted as requested. No extra text, no markdown headers, and no conversational language.



        <ADDITIONALUSERINSTRUCTIONS>

        {user_guideline}

        </ADDITIONALUSERINSTRUCTIONS>


        """
    return guideline_prompt
