# utils/compliance_utils.py

import json
from app import db
from app.models.project_instance_models import (
    ProjectComplianceActivity,
    ProjectClause,
    ProjectGuideline,
    ProjectControlActivity,
)
from sqlalchemy.orm import joinedload
from flask import current_app
from app.services.evaluation_prompt import generate_bulk_compliance_prompt
from app.utils.cleaning import generate_chat_output



def get_project_compliance_status(project_id):
    """
    Calculate overall compliance status for a project based on applicable activities.

    Returns:
    - 'compliant': All applicable activities are compliant
    - 'not-compliant': All applicable activities are not compliant
    - 'partially-compliant': Mix of compliance statuses among applicable activities
    - 'no-procedures': No applicable activities or no test procedures generated
    """

    # Get all activities for the project with their compliance activities
    activities = (
        db.session.query(ProjectComplianceActivity)
        .join(ProjectClause)
        .join(ProjectGuideline)
        .outerjoin(ProjectControlActivity)
        .filter(ProjectGuideline.project_id == project_id)
        .options(joinedload(ProjectComplianceActivity.project_control_activities))
        .all()
    )

    if not activities:
        return "no-procedures"

    # Filter only applicable activities
    applicable_activities = [act for act in activities if act.applicability == True]

    if not applicable_activities:
        return "no-procedures"

    # Check if any applicable activities have control activities
    has_control_activities = any(
        act.project_control_activities for act in applicable_activities
    )

    if not has_control_activities:
        return "no-procedures"

    # Get compliance statuses for applicable activities that have control activities
    compliance_statuses = []
    for activity in applicable_activities:
        if activity.project_control_activities:
            # Get the first (or only) control activity's status
            control_activity = activity.project_control_activities[0]
            if control_activity.compliant_status:
                compliance_statuses.append(control_activity.compliant_status)

    # If no applicable activities have compliance status yet
    if not compliance_statuses:
        return "no-procedures"

    # Apply business rules
    if all(status == "compliant" for status in compliance_statuses):
        return "compliant"
    elif all(status == "not-compliant" for status in compliance_statuses):
        return "not-compliant"
    else:
        # Mixed statuses (some compliant, some not, or partially compliant)
        return "partially-compliant"


def get_compliance_status_display_info(status):
    """
    Get display information for compliance status including CSS classes and text.
    """
    status_info = {
        "compliant": {
            "text": "Compliant",
            "css_class": "bg-green-200 text-green-800",
            "icon": "🟢",
        },
        "not-compliant": {
            "text": "Not Compliant",
            "css_class": "bg-red-200 text-red-800",
            "icon": "🔴",
        },
        "partially-compliant": {
            "text": "Partially Compliant",
            "css_class": "bg-yellow-200 text-yellow-800",
            "icon": "🟡",
        },
        "no-procedures": {
            "text": "To Be Assessed",
            "css_class": "bg-gray-200 text-gray-800",
            "icon": "⚪",
        },
    }

    return status_info.get(status, status_info["no-procedures"])


def get_clause_compliance_status(clause_activities):
    """
    Calculate compliance status for a specific clause based on its activities.

    Returns:
    - 'compliant': All applicable activities in the clause are compliant
    - 'not-compliant': All applicable activities in the clause are not compliant
    - 'partially-compliant': Mix of compliance statuses among applicable activities in the clause
    - 'no-procedures': No applicable activities or no test procedures generated for the clause
    """

    if not clause_activities:
        return "no-procedures"

    # Filter only applicable activities for this clause
    applicable_activities = [
        act for act in clause_activities if act.applicability == True
    ]

    if not applicable_activities:
        return "no-procedures"

    # Check if any applicable activities have control activities
    has_control_activities = any(
        act.project_control_activities for act in applicable_activities
    )

    if not has_control_activities:
        return "no-procedures"

    # Get compliance statuses for applicable activities that have control activities
    compliance_statuses = []
    for activity in applicable_activities:
        if activity.project_control_activities:
            control_activity = activity.project_control_activities[0]
            if control_activity.compliant_status:
                # Normalize: handle EVE V3 ("COMPLIANT","NON_COMPLIANT") and old ("Compliant","not-compliant")
                raw = control_activity.compliant_status.upper().replace(" ", "_").replace("-", "_")
                if raw in ("COMPLIANT",):
                    compliance_statuses.append("compliant")
                elif raw in ("NON_COMPLIANT", "NOT_COMPLIANT", "NONCOMPLIANT"):
                    compliance_statuses.append("not-compliant")
                elif raw in ("PARTIALLY_COMPLIANT", "PARTIAL",):
                    compliance_statuses.append("partially-compliant")
                # skip unknown statuses

    # If no applicable activities have compliance status yet
    if not compliance_statuses:
        return "no-procedures"

    # Apply business rules for this clause
    if all(status == "compliant" for status in compliance_statuses):
        return "compliant"
    elif all(status == "not-compliant" for status in compliance_statuses):
        return "not-compliant"
    else:
        return "partially-compliant"


def get_assessment_status(compliance_status, clause=None):
    """
    Get assessment status based on ProjectClause.assessment_status field (primary)
    or compliance_status (fallback).
    
    A clause is Completed when its assessment_status == "Completed" (set via Close Assessment button)
    regardless of whether it is compliant or non-compliant.
    A clause with findings reviewed + summary generated should also be Completed.
    """
    # Primary: use clause.assessment_status if available
    if clause is not None:
        clause_assessment_status = getattr(clause, 'assessment_status', None)
        if clause_assessment_status == "Completed":
            return {"text": "Completed", "css_class": "bg-green-200 text-green-800"}
    
    # Fallback: derive from compliance_status
    if compliance_status == "no-procedures":
        return {"text": "To Be Assessed", "css_class": "bg-gray-200 text-gray-800"}
    elif compliance_status in ["compliant", "not-compliant", "partially-compliant"]:
        return {"text": "In Progress", "css_class": "bg-orange-200 text-orange-800"}
    else:
        return {"text": "To Be Assessed", "css_class": "bg-gray-200 text-gray-800"}


def evaluate_single_activity_ai(control_activity, submitted_evidences, consolidated_files, 
                                test_procedure_info=None, activity_context=None, user_prompt=None):
    """
    Evaluate a single control activity using AI with detailed analysis
    Similar to your individual evaluation but for bulk processing
    """
    try:
        # Prepare evidence summary
        evidence_summary = []
        
        # Process submitted evidences
        for evidence in submitted_evidences:
            evidence_summary.append({
                "type": evidence.get("evidence_type", "submitted"),
                "item": evidence.get("item", "Unknown"),
                "description": evidence.get("evidence_text", ""),
                "files": evidence.get("files", ""),
                "has_content": bool(evidence.get("evidence_text") or evidence.get("files"))
            })
        
        # Process consolidated files
        for file in consolidated_files:
            evidence_summary.append({
                "type": file.get("evidence_type", "consolidated"),
                "item": "Uploaded Evidence File",
                "description": f"File: {file.get('filename', 'Unknown')} ({file.get('content_type', 'Unknown type')}) - Size: {file.get('size', 'Unknown')}",
                "files": file.get("file_path", ""),
                "has_content": True
            })
        
        # Generate the bulk evaluation prompt
        ai_prompt = generate_bulk_compliance_prompt(
            control_activity=control_activity,
            evidence_summary=evidence_summary,
            test_procedure_info=test_procedure_info,
            activity_context=activity_context,
            user_prompt=user_prompt
        )
        
        # Call your AI service
        ai_response = generate_chat_output(ai_prompt)
        
        # Parse the AI response
        if ai_response:
            try:
                # Extract JSON from response
                json_start = ai_response.find('```json')
                json_end = ai_response.find('```', json_start + 7)
                
                if json_start != -1 and json_end != -1:
                    json_str = ai_response[json_start + 7:json_end].strip()
                    output = json.loads(json_str)
                else:
                    # Try parsing entire response as JSON
                    output = json.loads(ai_response) if isinstance(ai_response, str) else ai_response
                
                # Validate the response structure
                if isinstance(output, dict) and "control_id" in output:
                    return {
                        "success": True,
                        "control_id": output.get("control_id"),
                        "activity_code": output.get("activity_code", control_activity.activity_code),
                        "compliant_status": output.get("overall_compliance_status", "not-compliant"),
                        "observation": output.get("observations", ""),
                        "findings": output.get("findings", ""),
                        "recommendations": output.get("recommendations", ""),
                        "risk_assessment": output.get("risk_assessment", ""),
                        "evidence_summary": output.get("evidence_summary", {}),
                        "evidence_count": len(evidence_summary),
                        "ai_evaluated": True,
                        "raw_response": ai_response[:500] + "..." if len(ai_response) > 500 else ai_response
                    }
                else:
                    # If JSON parsing fails, try to extract structured data
                    return parse_bulk_ai_response(ai_response, evidence_summary, control_activity, activity_context)
                    
            except json.JSONDecodeError as e:
                current_app.logger.warning(f"AI returned non-JSON response for activity {control_activity.id}: {str(e)}")
                # Fallback to parsing text response
                return parse_bulk_ai_response(ai_response, evidence_summary, control_activity, activity_context)
        
        # If AI fails, use enhanced logic-based evaluation
        return evaluate_with_enhanced_logic(evidence_summary, control_activity, activity_context)
        
    except Exception as e:
        current_app.logger.error(f"Error in bulk AI evaluation for activity {control_activity.id}: {str(e)}")
        return evaluate_with_enhanced_logic([], control_activity, activity_context)


def evaluate_with_enhanced_logic(evidence_summary, control_activity, activity_context=None):
    """
    Enhanced logic-based evaluation when AI fails
    """
    try:
        # Count valid evidence
        valid_evidence_count = sum(1 for e in evidence_summary if e.get('has_content', False))
        
        # Analyze evidence types
        has_documents = any('document' in str(e.get('description', '')).lower() or 
                           'text' in str(e.get('description', '')).lower() 
                           for e in evidence_summary)
        has_files = any(e.get('files') for e in evidence_summary)
        has_test_procedure = any(e.get('type') == 'test_procedure' for e in evidence_summary)
        
        # Determine compliance status with better logic
        if valid_evidence_count == 0:
            compliant_status = "not-compliant"
            observation = f"No evidence provided for control activity evaluation. [Clause: {activity_context.get('clause_no', 'N/A') if activity_context else 'N/A'} - {activity_context.get('project_name', 'N/A') if activity_context else 'N/A'}]"
            findings = "Cannot assess control effectiveness without evidence."
            recommendations = "Please implement the control and provide evidence of operation."
        
        elif valid_evidence_count >= 3 and has_documents and has_files:
            compliant_status = "compliant"
            observation = f"Comprehensive evidence provided including documentation and supporting files. Control appears effective. [Clause: {activity_context.get('clause_no', 'N/A') if activity_context else 'N/A'} - {activity_context.get('project_name', 'N/A') if activity_context else 'N/A'}]"
            findings = "Evidence suggests control is properly designed, implemented, and operating effectively."
            recommendations = "Continue current practices with regular monitoring and periodic reviews."
        
        elif valid_evidence_count >= 2 and (has_documents or has_files):
            compliant_status = "partially-compliant"
            observation = f"Some evidence provided but may be insufficient for full compliance. [Clause: {activity_context.get('clause_no', 'N/A') if activity_context else 'N/A'} - {activity_context.get('project_name', 'N/A') if activity_context else 'N/A'}]"
            findings = "Partial evidence available; additional documentation or verification may be required for full compliance assessment."
            recommendations = "Consider providing additional evidence such as implementation records, monitoring logs, or verification documents."
        
        else:
            compliant_status = "not-compliant"
            observation = f"Insufficient or incomplete evidence provided for compliance assessment. [Clause: {activity_context.get('clause_no', 'N/A') if activity_context else 'N/A'} - {activity_context.get('project_name', 'N/A') if activity_context else 'N/A'}]"
            findings = "Lack of adequate evidence to confirm control design, implementation, or operating effectiveness."
            recommendations = "Implement the control fully and provide comprehensive evidence including design documents, implementation records, and operating evidence."
        
        return {
            "success": True,
            "compliant_status": compliant_status,
            "observation": observation,
            "findings": findings,
            "recommendations": recommendations,
            "evidence_count": valid_evidence_count,
            "ai_evaluated": False
        }
        
    except Exception as e:
        current_app.logger.error(f"Error in enhanced logic evaluation: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "compliant_status": "not-compliant",
            "observation": "Evaluation error occurred",
            "evidence_count": 0,
            "ai_evaluated": False
        }


def parse_bulk_ai_response(ai_text, evidence_summary, control_activity, activity_context):
    """
    Parse AI text response for bulk evaluation when JSON parsing fails
    """
    try:
        # Initialize default values
        observation = ""
        findings = ""
        recommendations = ""
        compliant_status = "not-compliant"
        risk_assessment = ""
        
        # Extract sections using markers
        lines = ai_text.split('\n')
        
        # Try to extract Observations section
        obs_start = None
        obs_end = None
        for i, line in enumerate(lines):
            if 'Design Effectiveness:' in line or '**Design Effectiveness:**' in line:
                obs_start = i
            elif '**Findings:**' in line or '## Findings' in line or 'FINDINGS:' in line:
                obs_end = i
                break
        
        if obs_start is not None:
            if obs_end is not None:
                observation_lines = lines[obs_start:obs_end]
            else:
                observation_lines = lines[obs_start:]
            observation = '\n'.join(observation_lines).strip()
        
        # Try to extract Findings section
        find_start = None
        find_end = None
        for i, line in enumerate(lines):
            if '**Findings:**' in line or '## Findings' in line or 'FINDINGS:' in line:
                find_start = i
            elif '**Recommendations:**' in line or '## Recommendations' in line or 'RECOMMENDATIONS:' in line:
                find_end = i
                break
        
        if find_start is not None:
            if find_end is not None:
                finding_lines = lines[find_start:find_end]
            else:
                finding_lines = lines[find_start:]
            findings = '\n'.join(finding_lines).replace('**Findings:**', '').replace('## Findings', '').replace('FINDINGS:', '').strip()
        
        # Try to extract Recommendations section
        rec_start = None
        for i, line in enumerate(lines):
            if '**Recommendations:**' in line or '## Recommendations' in line or 'RECOMMENDATIONS:' in line:
                rec_start = i
                break
        
        if rec_start is not None:
            recommendation_lines = lines[rec_start:]
            recommendations = '\n'.join(recommendation_lines).replace('**Recommendations:**', '').replace('## Recommendations', '').replace('RECOMMENDATIONS:', '').strip()
        
        # Try to determine compliance status
        ai_text_lower = ai_text.lower()
        if 'compliant' in ai_text_lower and 'not-compliant' not in ai_text_lower and 'non-compliant' not in ai_text_lower:
            compliant_status = "compliant"
        elif 'partially-compliant' in ai_text_lower or 'partial compliance' in ai_text_lower:
            compliant_status = "partially-compliant"
        elif 'not-compliant' in ai_text_lower or 'non-compliant' in ai_text_lower:
            compliant_status = "not-compliant"
        
        # Add context if available
        if activity_context and observation:
            if '[Clause:' not in observation:
                observation += f" [Clause: {activity_context.get('clause_no', 'N/A')} - {activity_context.get('project_name', 'N/A')}]"
        
        return {
            "success": True,
            "control_id": control_activity.id,
            "activity_code": control_activity.activity_code,
            "compliant_status": compliant_status,
            "observation": observation,
            "findings": findings if findings else "No findings specified",
            "recommendations": recommendations if recommendations else "No recommendations specified",
            "risk_assessment": risk_assessment,
            "evidence_count": len(evidence_summary),
            "ai_evaluated": True,
            "parsed_from_text": True
        }
        
    except Exception as e:
        current_app.logger.error(f"Error parsing bulk AI text response: {str(e)}")
        return evaluate_with_enhanced_logic(evidence_summary, control_activity, activity_context)



def get_project_context_for_activity(project_control_activity):
    """
    Fetch the full project context for a control activity.
    Returns: dict with project, client, departments, guidelines, clause info
    """
    try:
        # Navigate through the relationships to get all context
        project_compliance_activity = project_control_activity.project_compliance_activity
        project_clause = project_compliance_activity.project_clause
        project_guideline = project_clause.project_guideline
        project = project_guideline.project
        
        # Get client info
        client_name = project.client_rel.name if project.client_rel else "No Client Assigned"
        
        # Get departments
        departments = []
        if project.departments:
            # Get unique department names
            unique_departments = []
            for dept in project.departments:
                if dept.department_name not in unique_departments:
                    unique_departments.append(dept.department_name)
            departments = unique_departments
        elif project.primary_department:
            departments = [project.primary_department.department_name]
        
        # Get guidelines
        guidelines = []
        if project.project_guidelines:
            for pg_item in project.project_guidelines:
                guidelines.append({
                    'id': pg_item.id,
                    'name': pg_item.guideline_data.get('DocumentDetails', {}).get('DocumentName', 'Unknown Guideline')
                })
        
        # Build context dictionary
        # Format assessment period
        assessment_start = project.assesment_start_date.strftime('%d %B %Y') if project.assesment_start_date else 'Not Specified'
        assessment_end = project.assesment_end_date.strftime('%d %B %Y') if project.assesment_end_date else 'Not Specified'
        assessment_period = f"{assessment_start} to {assessment_end}"

        context = {
            'project_id': project.id,
            'project_name': project.project_name,
            'project_description': project.project_description,
            'client_name': client_name,
            'departments': departments,
            'guidelines': guidelines,
            'clause_id': project_clause.id,
            'clause_no': project_clause.clause_no,
            'clause_text': project_clause.clause_text,
            'guideline_id': project_guideline.id,
            'guideline_name': project_guideline.guideline_data.get('DocumentDetails', {}).get('DocumentName', 'Unknown Guideline') if project_guideline.guideline_data else 'Unknown Guideline',
            'assessment_period': assessment_period,
            'assessment_start': assessment_start,
            'assessment_end': assessment_end,
        }
        
        return context
        
    except Exception as e:
        current_app.logger.error(f"Error fetching project context: {str(e)}")
        # Return minimal context if there's an error
        return {
            'project_name': 'Unknown Project',
            'client_name': 'Unknown Client',
            'departments': [],
            'project_description': '',
            'guidelines': [],
            'clause_id': None,
            'clause_no': 'Unknown',
            'clause_text': 'Unknown'
        }  




def get_project_clause_statistics(project_id):
    """Get clause statistics for a project"""
    try:
        # Get all project clauses
        project_clauses = db.session.query(ProjectClause).join(
            ProjectGuideline, ProjectClause.project_guideline_id == ProjectGuideline.id
        ).filter(
            ProjectGuideline.project_id == project_id
        ).all()
        
        total_clauses = len(project_clauses)
        applicable_clauses = sum(1 for clause in project_clauses if clause.applicability)
        not_applicable_clauses = total_clauses - applicable_clauses
        
        # Get compliance status for applicable clauses
        compliant_clauses = 0
        partially_compliant_clauses = 0
        non_compliant_clauses = 0
        completed_assessments = 0
        clauses_with_evidence = 0
        
        for clause in project_clauses:
            if clause.applicability:
                if hasattr(clause, 'assessment_status') and clause.assessment_status == "Completed":
                    completed_assessments += 1
                
                # Get all activities for this clause
                activities = db.session.query(ProjectControlActivity).join(
                    ProjectComplianceActivity,
                    ProjectControlActivity.project_compliance_activity_id == ProjectComplianceActivity.id
                ).filter(
                    ProjectComplianceActivity.project_clause_id == clause.id,
                    ProjectComplianceActivity.applicability == True
                ).all()
                
                # Check compliance status
                if activities:
                    all_compliant = all(hasattr(activity, 'compliant_status') and activity.compliant_status == 'Compliant' for activity in activities)
                    any_partial = any(hasattr(activity, 'compliant_status') and activity.compliant_status == 'Partially Compliant' for activity in activities)
                    
                    if all_compliant:
                        compliant_clauses += 1
                    elif any_partial:
                        partially_compliant_clauses += 1
                    else:
                        non_compliant_clauses += 1
                
                # Check if ALL activities have evidence
                all_activities_have_evidence = True
                for activity in activities:
                    evidence_received = (
                        hasattr(activity, 'evidence_admissibility_decision') and 
                        activity.evidence_admissibility_decision == "Yes" and 
                        hasattr(activity, 'evidence_quality_rating') and 
                        activity.evidence_quality_rating == "STRONG"
                    )
                    if not evidence_received:
                        all_activities_have_evidence = False
                        break
                
                if all_activities_have_evidence:
                    clauses_with_evidence += 1
        
        to_be_assessed = applicable_clauses - completed_assessments
        
        # Calculate percentages
        percentage_applicable = round((applicable_clauses / total_clauses * 100), 1) if total_clauses > 0 else 0
        percentage_completed = round((completed_assessments / applicable_clauses * 100), 1) if applicable_clauses > 0 else 0
        percentage_compliant = round((compliant_clauses / completed_assessments * 100), 1) if completed_assessments > 0 else 0
        percentage_partially_compliant = round((partially_compliant_clauses / completed_assessments * 100), 1) if completed_assessments > 0 else 0
        percentage_non_compliant = round((non_compliant_clauses / completed_assessments * 100), 1) if completed_assessments > 0 else 0
        
        # Return in the format your template expects
        return {
            'total_clauses': total_clauses,
            'applicability': {
                'applicable': applicable_clauses,
                'not_applicable': not_applicable_clauses,
                'percentage_applicable': percentage_applicable,
                'percentage_not_applicable': 100 - percentage_applicable if total_clauses > 0 else 0
            },
            'assessment': {
                'completed': completed_assessments,
                'to_be_assessed': to_be_assessed,
                'percentage_completed': percentage_completed,
                'percentage_to_be_assessed': 100 - percentage_completed if applicable_clauses > 0 else 0
            },
            'compliance': {
                'compliant': compliant_clauses,
                'partially_compliant': partially_compliant_clauses,
                'non_compliant': non_compliant_clauses,
                'total_assessed': completed_assessments,
                'percentage_compliant': percentage_compliant,
                'percentage_partially_compliant': percentage_partially_compliant,
                'percentage_non_compliant': percentage_non_compliant
            },
            'clauses_with_evidence': clauses_with_evidence
        }
    except Exception as e:
        print(f"Error in get_project_clause_statistics: {str(e)}")
        import traceback
        traceback.print_exc()
        # Return default values in the correct format
        return {
            'total_clauses': 0,
            'applicability': {
                'applicable': 0,
                'not_applicable': 0,
                'percentage_applicable': 0,
                'percentage_not_applicable': 0
            },
            'assessment': {
                'completed': 0,
                'to_be_assessed': 0,
                'percentage_completed': 0,
                'percentage_to_be_assessed': 0
            },
            'compliance': {
                'compliant': 0,
                'partially_compliant': 0,
                'non_compliant': 0,
                'total_assessed': 0,
                'percentage_compliant': 0,
                'percentage_partially_compliant': 0,
                'percentage_non_compliant': 0
            },
            'clauses_with_evidence': 0
        }
    
def get_project_severity_statistics(project_id):
    """Get severity statistics for a project"""
    try:
        severity_counts = {
            'Critical': 0,
            'Major': 0,
            'Significant': 0,
            'Minor': 0,
            'No findings noted': 0
        }
        
        # Get all project clauses
        project_clauses = db.session.query(ProjectClause).join(
            ProjectGuideline, ProjectClause.project_guideline_id == ProjectGuideline.id
        ).filter(
            ProjectGuideline.project_id == project_id,
            ProjectClause.applicability == True
        ).all()
        
        severity_hierarchy = {
            'Critical': 5,
            'Major': 4,
            'Significant': 3,
            'Minor': 2,
            'No findings noted': 1
        }
        
        for clause in project_clauses:
            # Get all activities for this clause
            activities = db.session.query(ProjectControlActivity).join(
                ProjectComplianceActivity,
                ProjectControlActivity.project_compliance_activity_id == ProjectComplianceActivity.id
            ).filter(
                ProjectComplianceActivity.project_clause_id == clause.id,
                ProjectComplianceActivity.applicability == True
            ).all()
            
            # Find highest severity for this clause
            highest_severity = 'No findings noted'
            highest_score = 0
            
            for activity in activities:
                raw_severity = activity.overall_severity_classification
                
                # Normalize EVE V3 severity values to standard labels
                severity_map = {
                    'CRITICAL': 'Critical', 'Critical': 'Critical',
                    'HIGH': 'Major', 'High': 'Major', 'MAJOR': 'Major', 'Major': 'Major',
                    'MEDIUM': 'Significant', 'Medium': 'Significant',
                    'SIGNIFICANT': 'Significant', 'Significant': 'Significant',
                    'LOW': 'Minor', 'Low': 'Minor', 'MINOR': 'Minor', 'Minor': 'Minor',
                    'NO_FINDINGS': 'No findings noted', 'No findings noted': 'No findings noted',
                    'NO FINDINGS NOTED': 'No findings noted',
                }
                activity_severity = severity_map.get(raw_severity, None)
                
                if not activity_severity:
                    # Fallback — check compliant status
                    raw_cs = (activity.compliant_status or '').upper().replace('-','_').replace(' ','_')
                    if raw_cs == 'COMPLIANT':
                        activity_severity = 'No findings noted'
                    else:
                        activity_severity = None
                
                if activity_severity and activity_severity != 'Not Classified':
                    severity_score = severity_hierarchy.get(activity_severity, 0)
                    if severity_score > highest_score:
                        highest_score = severity_score
                        highest_severity = activity_severity
            
            if highest_severity in severity_counts:
                severity_counts[highest_severity] += 1
            else:
                severity_counts['No findings noted'] += 1
        
        # Calculate total non-compliant findings
        total_findings = severity_counts['Critical'] + severity_counts['Major'] + severity_counts['Significant'] + severity_counts['Minor']
        
        return {
            'counts': severity_counts,
            'total_findings': total_findings
        }
    except Exception as e:
        print(f"Error in get_project_severity_statistics: {str(e)}")
        return {
            'counts': {
                'Critical': 0,
                'Major': 0,
                'Significant': 0,
                'Minor': 0,
                'No findings noted': 0
            },
            'total_findings': 0
        }


def get_project_evidence_statistics(project_id):
    """Get evidence statistics for a project"""
    try:
        clauses_with_evidence = 0
        clauses_without_evidence = 0
        
        # Get all project clauses
        project_clauses = db.session.query(ProjectClause).join(
            ProjectGuideline, ProjectClause.project_guideline_id == ProjectGuideline.id
        ).filter(
            ProjectGuideline.project_id == project_id,
            ProjectClause.applicability == True
        ).all()
        
        for clause in project_clauses:
            # Get all activities for this clause
            activities = db.session.query(ProjectControlActivity).join(
                ProjectComplianceActivity,
                ProjectControlActivity.project_compliance_activity_id == ProjectComplianceActivity.id
            ).filter(
                ProjectComplianceActivity.project_clause_id == clause.id,
                ProjectComplianceActivity.applicability == True
            ).all()
            
            # Check if ALL activities have evidence
            all_activities_have_evidence = True
            
            for activity in activities:
                evidence_received = (
                    activity.evidence_admissibility_decision in ("Yes", "YES", "ADMISSIBLE")
                )
                if not evidence_received:
                    all_activities_have_evidence = False
                    break
            
            if all_activities_have_evidence:
                clauses_with_evidence += 1
            else:
                clauses_without_evidence += 1
        
        total_applicable = clauses_with_evidence + clauses_without_evidence
        evidence_percentage = round((clauses_with_evidence / total_applicable * 100)) if total_applicable > 0 else 0
        
        return {
            'with_evidence': clauses_with_evidence,
            'without_evidence': clauses_without_evidence,
            'total': total_applicable,
            'percentage': evidence_percentage
        }
    except Exception as e:
        print(f"Error in get_project_evidence_statistics: {str(e)}")
        return {
            'with_evidence': 0,
            'without_evidence': 0,
            'total': 0,
            'percentage': 0
        }          