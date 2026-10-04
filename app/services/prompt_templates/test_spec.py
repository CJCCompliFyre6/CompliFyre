"""
Test specification (Phase 1 of full-population testing) - GRACE.

For every control, decide HOW operating effectiveness is tested and write the specification EVE executes:
  * population_data  - a full data extract; every instance in the audit period is tested in code
                       (extends the attribute format used by app/services/attribute_testing_engine.py)
  * document_review  - every document in the audit period (e.g. all committee minutes) is read and checked
  * design_only      - no operating-effectiveness population (one-off / existence requirements)
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field

AttrType = Literal["text", "number", "amount", "date", "datetime", "boolean"]
FilterType = Literal["equals", "not_equals", "in_list", "not_in_list", "contains", "greater_than", "greater_or_equal", "less_than", "less_or_equal", "not_empty"]
Comparator = Literal["<=", "<", ">=", ">", "="]
TestType = Literal["presence_check", "value_match", "in_list", "numeric_threshold", "date_difference",
                   "on_or_before", "different_from", "compare_fields", "conditional",
                   "count_per_period", "max_gap"]


class AttributeDef(BaseModel):
    name: str = Field(..., description="snake_case name used inside this spec, e.g. detection_datetime")
    column_description: str = Field(..., description="Plain description used to find the bank's column, e.g. 'Date and time the incident was detected'")
    type: AttrType
    key: bool = Field(False, description="True if this attribute decides compliance (a key attribute)")


class RejectedDate(BaseModel):
    attribute: str
    reason_rejected: str


class PeriodDate(BaseModel):
    attribute: str = Field(..., description="The ONE date attribute that decides whether an instance belongs to the audit period")
    rationale: str
    considered_and_rejected: list[RejectedDate] = Field(default_factory=list)


class PopulationFilter(BaseModel):
    testing_sequence: int = Field(..., description="Order in which the filter is applied (1 = first, after the period filter)")
    attribute: str
    filter_type: FilterType
    filter_value: Optional[str] = Field(None, description="Single value (number written as text) for equals / not_equals / contains / greater_than / less_than")
    filter_values: Optional[list[str]] = Field(None, description="Values for in_list / not_in_list")
    why: str


class DerivedValue(BaseModel):
    name: str
    formula: str = Field(..., description="Formula over attributes, e.g. 'hours_between(detection_datetime, rbi_reported_datetime)', "
                                          "'outstanding * lookup(provision_rate_table, asset_class, age_band)', 'required_provision - provision_held'")
    unit: Optional[str] = None


class TestAttribute(BaseModel):
    attribute_name: str = Field(..., description="Short name of the test, e.g. 'Reported within 6 hours'")
    testing_sequence: int
    test_type: TestType
    test_attribute: str = Field(..., description="Attribute (or derived value) tested")
    second_attribute: Optional[str] = Field(None, description="Second attribute for date_difference / on_or_before / different_from / compare_fields")
    comparator: Optional[Comparator] = Field(None, description=(
        "Direction of the test, never implied: numeric_threshold -> test_attribute <comparator> threshold; "
        "date_difference -> (second_attribute minus test_attribute, in threshold_unit) <comparator> threshold; "
        "compare_fields -> test_attribute <comparator> second_attribute. on_or_before always means test_attribute <= second_attribute."))
    threshold: Optional[float] = None
    threshold_unit: Optional[str] = Field(None, description="hours / days / months / percent / INR")
    expected_value: Optional[str] = None
    expected_values: Optional[list[str]] = Field(None, description="For in_list")
    condition: Optional[str] = Field(None, description="For 'conditional': 'when <condition> then <requirement>', e.g. 'when days_past_due > 90 then asset_classification = NPA'")
    period: Optional[Literal["monthly", "quarterly", "half_yearly", "annually"]] = Field(None, description="For count_per_period / max_gap")
    exception_identifier_attribute: str = Field(..., description="Attribute that identifies an instance in the exception list, e.g. incident_id")
    pass_criteria: str
    fail_criteria: str
    reason_code: str = Field(..., description="Short code shown for a failure, e.g. NC2_LATE")
    severity_if_failed: Literal["Critical", "Significant", "Moderate", "Minor"]
    regulatory_reference: str = Field(..., description="The clause wording this test comes from")


class NonCompliance(BaseModel):
    reason_code: str
    meaning: str


class ComplianceDefinition(BaseModel):
    compliant: str
    non_compliant: list[NonCompliance]
    not_assessable: str


class Impact(BaseModel):
    attribute: Optional[str] = Field(None, description="Attribute or derived value that best measures impact (amount, shortfall, hours late ...)")
    measure: str = Field(..., description="How it is totalled, e.g. 'sum of shortfall (INR)', 'count of exceptions and maximum hours late'")
    financial: bool
    fallback: Optional[str] = None


class PopulationDataSpec(BaseModel):
    dataset_name: str
    one_row_is: str
    data_request: str = Field(..., description="Text of the evidence request to the bank: full extract (CSV or Excel, not zipped) with the listed fields for the audit period")
    attributes: list[AttributeDef]
    period_date: PeriodDate
    population_filters: list[PopulationFilter] = Field(default_factory=list)
    derived_values: list[DerivedValue] = Field(default_factory=list)
    lookup_tables: Optional[str] = Field(None, description="Rate tables copied verbatim from the clause, written as JSON text, e.g. provisioning rates by asset class and age band")
    test_attributes: list[TestAttribute]
    key_attributes: list[str]
    compliance_definition: ComplianceDefinition
    impact: Impact
    analyse_exceptions_by: list[str] = Field(default_factory=list)
    validation_checks: list[str] = Field(default_factory=list, description="Checks before testing, e.g. 'incident_id unique', 'period fully covered'")
    completeness_check: Optional[str] = Field(None, description="How to confirm the extract is the COMPLETE population, e.g. reconcile incident count with SOC tickets classified as incidents")
    judgement_items: list[str] = Field(default_factory=list, description="Things that cannot be tested mechanically and need auditor judgement")


class Fact(BaseModel):
    name: str
    description: str


class DocumentRule(BaseModel):
    rule_type: Literal["frequency", "quorum", "agenda_coverage", "approval", "timeliness", "attendance", "content", "other"]
    requirement: str
    period: Optional[Literal["monthly", "quarterly", "half_yearly", "annually"]] = None
    min_count_per_period: Optional[int] = Field(None, description="For frequency: minimum number of events in EACH period, e.g. 1 in each quarter")
    required_items: list[str] = Field(default_factory=list, description="For agenda_coverage / content: the specific items the clause makes this body responsible for, listed from the clause")
    source: Literal["clause", "tor_or_charter"] = Field("clause", description="Where the requirement comes from: the clause, or (only where the clause is silent) the body's TOR / charter")
    pass_criteria: str
    fail_criteria: str
    reason_code: str
    regulatory_reference: str


class DocumentReviewSpec(BaseModel):
    documents_required: list[str] = Field(..., description="Every document of this kind in the audit period, e.g. 'All ITSC meeting minutes for the audit period'")
    reference_documents: list[str] = Field(default_factory=list, description="Documents the rules depend on, e.g. 'ITSC Terms of Reference (quorum, composition)'")
    facts_to_extract: list[Fact]
    rules: list[DocumentRule]
    compliance_definition: ComplianceDefinition
    impact: Impact


class DesignOnlySpec(BaseModel):
    documents_required: list[str] = Field(..., description="Documents the BANK provides; never auditor working papers such as interview notes")
    checks: list[str]


class TestSpec(BaseModel):
    test_mode: Literal["population_data", "document_review", "design_only"]
    rationale: str
    population_data: Optional[PopulationDataSpec] = None
    document_review: Optional[DocumentReviewSpec] = None
    design_only: Optional[DesignOnlySpec] = None


def test_spec_prompt(clause_text: str, control: dict, test_procedure: dict, evidence: list[str]) -> str:
    return f"""You are a senior IT and regulatory auditor designing how a control's OPERATING EFFECTIVENESS will be tested
for an Indian NBFC. The bank requires FULL-POPULATION testing: every instance in the audit period is tested - no sampling.

REGULATORY CLAUSE (verbatim):
{clause_text}

CONTROL:
- Name: {control.get('activity_name')}
- Description: {control.get('activity_description')}
- Frequency: {control.get('frequency')} | Type: {control.get('control_type')}
- Tested for: design={control.get('dimension_design')}, implementation={control.get('dimension_implementation')}, operating={control.get('dimension_operating')}

TEST PROCEDURE ALREADY WRITTEN:
- Walkthrough: {test_procedure.get('walkthrough')}
- Earlier sampling note (to be replaced by full-population testing): {test_procedure.get('sampling')}

EVIDENCE LIST: {evidence}

STEP 1 - CHOOSE THE TEST MODE:
- design_only: the control is not tested for operating effectiveness (operating=False), or it is a one-off / existence
  requirement (a policy exists and is approved, a function is set up).
- document_review: recurring events evidenced by a SMALL number of documents - committee or Board meetings, annual or
  periodic reviews, periodic reports, approvals. Banks do NOT keep these in spreadsheets; every document of that kind in the
  audit period is read (e.g. all ITSC minutes) and checked for frequency, quorum, agenda coverage, approvals, timeliness.
- population_data: high-volume transactions or records held in systems (incidents, access requests, changes, loans,
  provisions, transfers, complaints, returns filed ...) that the bank can export as a CSV / Excel extract.
  Choose population_data ONLY when the clause states a requirement that can be tested on EACH instance (a deadline, a limit,
  a rate, a sequence, a prohibition, an approval). A clause that only says the RE shall HAVE a control, policy, process or
  framework ("have access controls and a password policy") is design_only or document_review - never invent per-event flags
  to force a data test.

STEP 2 - WRITE THE SPECIFICATION FOR THAT MODE ONLY (leave the other two null).

For population_data, make every judgement explicit - EVE will refuse to test until these preconditions are met:
0. THE POPULATION is every event that TRIGGERS the obligation (all detected incidents, all access requests, all loans
   transferred) - never only the outputs (incidents reported, approvals given). Otherwise the most serious failure - the action
   never taken - is invisible. Give a completeness_check against a second source where one exists.
1. attributes: only the fields actually needed; each with a plain column_description (used to find the bank's column) and type.
2. period_date: the ONE date that decides whether an instance falls in the audit period, and why. List the other dates you
   considered and why they were rejected (e.g. using the reporting date would drop incidents detected in period but never
   reported). The period filter is always applied first.
3. population_filters: AFTER the period filter, the filters that narrow the data to what the clause actually covers
   (e.g. only reportable incidents, exclude duplicates, exclude a portfolio the clause excludes), in the order applied, each with why.
   Applicability of the ENTITY (e.g. "not applicable to HFCs", asset-size thresholds) is NEVER a row filter.
4. derived_values and lookup_tables: anything to compute (hours between two dates, a required amount from a rate table).
   Rate tables must be copied EXACTLY from the clause - never invent a threshold, rate or deadline the clause does not state.
5. test_attributes: one per rule, in testing order, using test_type:
   presence_check, value_match, in_list, numeric_threshold, date_difference (second_attribute + threshold + unit),
   on_or_before, different_from, compare_fields (test_attribute vs second_attribute), conditional (condition 'when ... then ...'),
   count_per_period / max_gap (period-level rules). Each with pass/fail criteria, a reason_code and the clause wording.
   Always set the comparator - the direction of a test must never be implied by its wording.
   For every deadline: FIRST a presence test (the action was done at all - reason e.g. NC1_NOT_DONE), THEN the timeliness test.
   Test FACTS (dates, amounts, values, who approved) - not flags the bank fills in about itself ("evaluated = Yes"). If only a
   self-declared flag exists, test it but also list it under judgement_items for the auditor to verify.
6. key_attributes: the attributes that decide compliance.
7. compliance_definition: what is compliant; each non-compliance reason_code and meaning; what is NOT ASSESSABLE
   (a key value missing or unreadable - never treated as compliant).
8. impact: the attribute or derived value that best measures impact. Whenever an instance carries a money value (loan amount,
   exposure, transaction value, shortfall), include that attribute and use it - financial = true, totalled in INR. Otherwise
   count, delay, missed periods. Give a fallback.
9. analyse_exceptions_by: dimensions useful to find a root cause (month, branch, product, approver, severity ...).
10. validation_checks, judgement_items, and data_request (the text asking the bank for the full extract with these fields
    for the audit period, as CSV or Excel, not zipped).

For document_review - this applies to ANY committee or Board (ITSC, IT Steering Committee, ISC, Audit Committee, Risk
Management Committee, the Board ...) and to any recurring, document-evidenced obligation (annual policy review, periodic
report to the Board, periodic return). Every rule comes from what the clause requires of the RE:
- frequency: the clause's own wording, applied PER PERIOD (min_count_per_period events in EACH quarter / half-year / year).
  If the clause states no frequency, use the body's TOR / charter frequency (source = tor_or_charter) - never invent one.
- agenda_coverage / content: required_items = the specific matters the clause makes that body responsible for, listed from the
  clause; each must be taken up across the period's minutes.
- quorum / composition: from the clause if it says anything; otherwise from the TOR / charter (add it to reference_documents).
- approval / timeliness: only where the clause asks for them.
Give documents_required (every document of the kind in the audit period), reference_documents, facts_to_extract from each
document, compliance_definition and impact (e.g. periods missed, meetings without quorum, required items never taken up).

For design_only: documents_required (documents the bank provides - never auditor working papers such as interview notes) and
the checks (exists, approved by the right authority, covers the clause's required content).

Keep the regulation's own terms and abbreviations. Return ONLY the JSON object."""
