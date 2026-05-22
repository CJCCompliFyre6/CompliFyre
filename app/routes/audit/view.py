from threading import Thread
from flask import (
    Blueprint,
    request,
    jsonify,
    current_app,
    render_template,
    url_for,
    redirect,
    flash,
    send_from_directory,
    abort,
    session,
    Response,
)

import redis
from datetime import datetime
from app.utils.extract_clause_helper import check_free_report_used

from datetime import datetime
# from app import limiter
from app.services.manual_task import (
    generate_consolidated_test_procedure,
    generate_consolidated_observation_summary,
    generate_consolidated_findings_summary,
    generate_consolidated_recommendations_summary,
    consolidate_evidence_task,
    get_redis_connection,
    debug_redis_connection,
)
from app.routes.main import _json_response
from app.services.pdf_service import PDFService
from app.utils.exceptions import PDFServiceError, URLValidationError
from marshmallow import Schema, fields, ValidationError
from app.models.auditOrganization import *
from app.models.organization import *
from app.models.ai import *
from sqlalchemy.exc import *
from app.models.organization import *
from app.models.auditLog import AuditLogs
from app.utils.user_helpers import create_user_for_contact, create_user_direct_sql_fixed
import os, json
from sqlalchemy.orm import joinedload, subqueryload
from sqlalchemy import select
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from collections import defaultdict
from werkzeug.utils import secure_filename
from app.utils.cleaning import *
from app.services.prompt_service import *
from app.models.user import *
import random
import string
from app.services.evaluation_prompt import *
from app.models.project_instance_models import *
from app.utils.bread_crumb import add_to_breadcrumb
from app.utils.permission_handler import role_required
from app.services.model_response import *
from app.utils.email_service import (
    send_contact_credentials_email,
    send_guideline_request_email,
)
from app.utils.compliance_utils import (
    get_project_context_for_activity,
    get_project_clause_statistics,
    get_project_severity_statistics,
    get_project_evidence_statistics)

from app.models.organization import OrganizationContacts
from app.services.prompt_templates.interview_answer_prompt import *

audit_bp = Blueprint(
    "audit",
    __name__,
    template_folder="../../templates/dashboards/auditor",
    static_folder="../../templates/dashboards/auditor/assets",
)
UPLOAD_FOLDER_MOM = "uploads/minute_of_meeting"
os.makedirs(UPLOAD_FOLDER_MOM, exist_ok=True)


class TaskStatus:
    """
    Minimal helper to record Celery task status into Redis so the SSE progress
    endpoint can read it. This avoids NameError if a TaskStatus model/class is
    not available elsewhere. Use existing Redis connection and store under key
    'evidence_progress:{task_id}' as JSON.
    """

    def __init__(self, redis_conn=None):
        self.redis = redis_conn or get_redis_connection()

    def set_status(self, task_id, user_id, task_name, status, progress=0, message=""):
        payload = {
            "task_id": task_id,
            "user_id": user_id,
            "task_name": task_name,
            "status": status,
            "progress": progress,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
        }
        try:
            self.redis.set(f"evidence_progress:{task_id}", json.dumps(payload))
        except Exception as e:
            # Log using Flask logger if available; fallback to print
            try:
                current_app.logger.error(f"TaskStatus.set_status redis error: {e}")
            except Exception:
                print(f"TaskStatus.set_status redis error: {e}")


UPLOAD_FOLDER_MOM = "uploads/minute_of_meeting"
os.makedirs(UPLOAD_FOLDER_MOM, exist_ok=True)
os.makedirs(UPLOAD_FOLDER_MOM, exist_ok=True)


@audit_bp.route("/", methods=["GET"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def dashboard():
    """
    Dashboard route for the RE application.
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        add_to_breadcrumb(request.full_path, "Auditor Dashboard")
        organization = None
        if current_user.is_authenticated:
            organization = AuditOrganization.query.filter_by(
                id=current_user.auditor_profile_id
            ).first()
            clients = (
                db.session.query(auditor_client)
                .filter(auditor_client.c.audit_id == current_user.auditor_profile_id)
                .all()
            )
            projects = Projects.query.filter_by(
                auditing_firm=current_user.auditor_profile_id
            ).all()
            all_proj = {proj.project_name for proj in projects}
            all_guidelines = Guidelines.query.filter_by(enabled=True).all()
            print(all_proj)
            info_data = {
                "total_clients": len(clients),
                "total_projects": len(all_proj),
                "total_guidelines": len(all_guidelines),
            }
        return render_template(
            "audit_dash.html", organization=organization, info_data=info_data
        )
    except PDFServiceError as pdf_err:
        current_app.logger.error(f"PDF Service Error: {str(pdf_err)}")
        return jsonify({"error": "Error with PDF service"}), 500
    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/add", methods=["GET"])
def add():
    """
    Add
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("add.html")
    except PDFServiceError as pdf_err:
        current_app.logger.error(f"PDF Service Error: {str(pdf_err)}")
        return jsonify({"error": "Error with PDF service"}), 500
    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/create_orginization", methods=["GET"])
def create_organization():
    """
    Create organization page
    """
    try:
        return render_template("create_profile.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/test_email_delivery")
def test_email_delivery():
    """Test if emails are actually being delivered"""
    try:
        success = send_contact_credentials_email(
            contact_email="shruzzekbote@gmail.com",
            contact_name="Test User",
            organization_name="Test Organization",
            login_url="http://127.0.0.1:5000/login",
            temp_password="TestPass123",
        )

        if success:
            return """
            <h1>✅ Email Sent Successfully!</h1>
            <p>The email was sent successfully from the SMTP server.</p>
            <p><strong>Next steps:</strong></p>
            <ol>
                <li>Check the spam/junk folder in Gmail</li>
                <li>Wait 5-10 minutes for delivery</li>
                <li>Check email headers for delivery status</li>
            </ol>
            <p>If still not received, there might be delivery issues with the receiving server.</p>
            """
        else:
            return "<h1>❌ Email Failed to Send</h1><p>Check the server logs for details.</p>"

    except Exception as e:
        return f"<h1>Error</h1><p>{str(e)}</p>"


@audit_bp.route("/edit_profile", methods=["GET", "POST"])
@login_required
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def edit_profile():
    add_to_breadcrumb(request.full_path, "Edit Profile")
    try:
        # 🔹 Get current user's org
        user = Users.query.filter_by(email=current_user.email).first()

        if not user or not user.auditor_profile_id:
            flash("User profile not found.", "error")
            return redirect(url_for("audit.dashboard"))

        org = AuditOrganization.query.get(user.auditor_profile_id)

        if not org:
            flash("Organization profile not found.", "error")
            return redirect(url_for("audit.dashboard"))

        if request.method == "GET":
            # 🔹 Fetch all related data with debugging

            # Get contact persons
            contact_persons = AuditOrgContactPerson.query.filter_by(
                audit_org_id=org.id
            ).all()
            print(
                f"DEBUG: Found {len(contact_persons)} contact persons for org {org.id}"
            )
            for cp in contact_persons:
                print(
                    f"DEBUG: Contact - Name: {cp.name}, Email: {cp.email}, Phone: {cp.phone}"
                )

            # Get head office address
            head_office_address = AuditOrgAddress.query.filter_by(
                audit_org_id=org.id, head_office=True
            ).first()

            if head_office_address:
                print(
                    f"DEBUG: Head Office - {head_office_address.address}, {head_office_address.city}, {head_office_address.state}, {head_office_address.country}"
                )
            else:
                print("DEBUG: No head office address found")

            # Get certifications
            certifications = OrgAuditCertifications.query.filter_by(
                audit_org_id=org.id
            ).all()
            current_certification = (
                certifications[0].certifications if certifications else ""
            )

            # Get focus areas
            focus_areas_list = OrgAuditFocusAreas.query.filter_by(
                audit_org_id=org.id
            ).all()
            current_focus_areas = (
                ", ".join([fa.focus_area for fa in focus_areas_list])
                if focus_areas_list
                else ""
            )

            # Get hierarchy
            hierarchy = AuditOrgHierarchy.query.filter_by(audit_org_id=org.id).all()
            print(f"DEBUG: Found {len(hierarchy)} hierarchy items")
            for h in hierarchy:
                print(f"DEBUG: Hierarchy - Post: {h.post}, Reports To: {h.reports_to}")

            print(
                f"DEBUG: Organization details - Name: {org.firm_name}, Description: {org.firm_description}, Employees: {org.number_of_employees}"
            )

            return render_template(
                "edit_profile.html",
                org=org,
                contact_persons=contact_persons,
                head_office_address=head_office_address,
                current_certification=current_certification,
                current_focus_areas=current_focus_areas,
                hierarchy=hierarchy,
            )

        elif request.method == "POST":
            # Step 1: Update Organization Info
            org.firm_name = request.form.get("org_name", "").strip()
            org.firm_registration_no = request.form.get("org_reg_no", "").strip()
            org.firm_description = request.form.get("description", "").strip()

            num_employees = request.form.get("num_employees", "").strip()
            if num_employees and num_employees.isdigit():
                org.number_of_employees = int(num_employees)

            # Step 2: Update Head Office Address
            address = request.form.get("address", "").strip()
            country = request.form.get("country", "").strip()
            state = request.form.get("state", "").strip()
            city = request.form.get("city", "").strip()

            if address or country or state or city:
                # Update or create head office address
                head_office_addr = AuditOrgAddress.query.filter_by(
                    audit_org_id=org.id, head_office=True
                ).first()

                if head_office_addr:
                    head_office_addr.address = address
                    head_office_addr.country = country
                    head_office_addr.state = state
                    head_office_addr.city = city
                else:
                    head_office_addr = AuditOrgAddress(
                        audit_org_id=org.id,
                        address=address,
                        country=country,
                        state=state,
                        city=city,
                        head_office=True,
                    )
                    db.session.add(head_office_addr)

            # Step 3: Update Contact Persons
            # Clear existing contact persons
            AuditOrgContactPerson.query.filter_by(audit_org_id=org.id).delete()

            names = request.form.getlist("name_person[]")
            emails = request.form.getlist("email_person[]")
            phones = request.form.getlist("phone_person[]")

            print(
                f"DEBUG: Received contact data - Names: {names}, Emails: {emails}, Phones: {phones}"
            )

            for name, email, phone in zip(names, emails, phones):
                if name.strip() or email.strip() or phone.strip():
                    contact_person = AuditOrgContactPerson(
                        audit_org_id=org.id,
                        name=name.strip(),
                        email=email.strip(),
                        phone=phone.strip(),
                    )
                    db.session.add(contact_person)
                    print(
                        f"DEBUG: Adding contact - {name.strip()}, {email.strip()}, {phone.strip()}"
                    )

            # Step 4: Certification upload
            cert_file = request.files.get("certifications")
            if cert_file and cert_file.filename != "":
                filename = secure_filename(cert_file.filename)
                cert_path = os.path.join(
                    current_app.root_path, "static/uploads", filename
                )

                # Ensure uploads directory exists
                os.makedirs(os.path.dirname(cert_path), exist_ok=True)
                cert_file.save(cert_path)

                # Update or create certification record
                existing_cert = OrgAuditCertifications.query.filter_by(
                    audit_org_id=org.id
                ).first()
                if existing_cert:
                    existing_cert.certifications = filename
                else:
                    new_cert = OrgAuditCertifications(
                        audit_org_id=org.id, certifications=filename
                    )
                    db.session.add(new_cert)

            # Step 5: Focus Areas
            focus_areas_input = request.form.get("focus_areas", "").strip()
            if focus_areas_input:
                # Clear existing focus areas
                OrgAuditFocusAreas.query.filter_by(audit_org_id=org.id).delete()

                # Add new focus areas (split by comma)
                focus_areas_list = [
                    fa.strip() for fa in focus_areas_input.split(",") if fa.strip()
                ]
                for focus_area in focus_areas_list:
                    fa_record = OrgAuditFocusAreas(
                        audit_org_id=org.id, focus_area=focus_area
                    )
                    db.session.add(fa_record)

            # Step 6: Hierarchy
            print(f"DEBUG: Processing hierarchy data...")
            AuditOrgHierarchy.query.filter_by(
                audit_org_id=org.id
            ).delete()  # Clear existing
            titles = request.form.getlist("hierarchy_title[]")
            names = request.form.getlist("hierarchy_name[]")

            print(f"DEBUG: Hierarchy titles: {titles}")
            print(f"DEBUG: Hierarchy names: {names}")

            for title, name in zip(titles, names):
                if title.strip() or name.strip():
                    hierarchy_item = AuditOrgHierarchy(
                        audit_org_id=org.id,
                        post=title.strip(),  # Note: using 'post' as per your model
                        reports_to=name.strip(),  # Note: using 'reports_to' as per your model
                    )
                    db.session.add(hierarchy_item)
                    print(
                        f"DEBUG: Adding hierarchy - Post: {title.strip()}, Reports To: {name.strip()}"
                    )

            db.session.commit()
            flash("Profile updated successfully.", "success")
            return redirect(url_for("audit.edit_profile"))

    except SQLAlchemyError as err:
        db.session.rollback()
        current_app.logger.error(f"DB Error during edit_profile: {err}")
        flash("A database error occurred.", "error")
        return redirect(url_for("audit.edit_profile"))

    except Exception as err:
        db.session.rollback()
        current_app.logger.error(f"Unexpected error in edit_profile: {err}")
        flash("An unexpected error occurred.", "error")
        return redirect(url_for("audit.edit_profile"))


@audit_bp.route("/approved", methods=["GET"])
def approved():
    """
    approved audit plan page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("appr.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/ctl", methods=["GET"])
def ctl():
    """
    Control Testing Results page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("ctl.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/dam", methods=["GET"])
def dam():
    """
    Dam page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("dam.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/det", methods=["GET"])
def det():
    """
    Det page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("det.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/eng", methods=["GET"])
def eng():
    """
    eng page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("eng.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/eva", methods=["GET"])
def eva():
    """
    eva page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("eva.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/final", methods=["GET"])
def final():
    """
    final page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("final.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/find", methods=["GET"])
def find():
    """
    find page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("find.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/mat", methods=["GET"])
def mat():
    """
    mat page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("mat.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/memo", methods=["GET"])
def memo():
    """
    memo page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("memo.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/new", methods=["GET"])
def new():
    """
    new page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("new.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/note", methods=["GET"])
def note():
    """
    note page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("note.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/plan", methods=["GET"])
def plan():
    """
    plan page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("plan.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/prog", methods=["GET"])
def prog():
    """
    prog page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("prog.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/resp", methods=["GET"])
def resp():
    """
    resp page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("resp.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/risk", methods=["GET"])
def risk():
    """
    risk page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("risk.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/scop", methods=["GET"])
def scop():
    """
    scop page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("scop.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/stat", methods=["GET"])
def stat():
    """
    stat page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("stat.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/subs", methods=["GET"])
def subs():
    """
    subs page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("subs.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/view", methods=["GET"])
def view():
    """
    view page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("view.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/work", methods=["GET"])
def work():
    """
    work page
    """
    try:
        # pdf_service = PDFService()
        # guidelines = pdf_service.get_guidelines()
        return render_template("work.html")

    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/manage_profile", methods=["GET"])
def manage_profile():
    """
    manage profile page
    """
    try:

        return render_template("manage_profile.html")
    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


# request new guideline route
@audit_bp.route("/request_guideline", methods=["GET", "POST"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def request_guideline():
    """Handle new guideline requests"""
    form = GuidelineRequestForm()

    if form.validate_on_submit():
        try:
            # Validate that at least one of web_link or attachment is provided
            if not form.web_link.data and not form.attachment.data:
                flash(
                    "Please provide either a web link or attach the guideline PDF",
                    "error",
                )
                return render_template("request_guideline.html", form=form)

            # Handle file upload if present
            attachment_path = None
            if form.attachment.data:
                filename = secure_filename(form.attachment.data.filename)
                # Create unique filename
                unique_filename = f"{current_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"

                # Create uploads/guideline_requests directory if it doesn't exist
                upload_dir = os.path.join(
                    current_app.config["UPLOAD_FOLDER"], "guideline_requests"
                )
                os.makedirs(upload_dir, exist_ok=True)

                upload_path = os.path.join(upload_dir, unique_filename)
                form.attachment.data.save(upload_path)
                attachment_path = upload_path

            # Create guideline request record with initial status
            guideline_request = GuidelineRequest(
                user_id=current_user.id,
                guideline_name=form.guideline_name.data,
                regulator_name=form.regulator_name.data,
                web_link=form.web_link.data,
                attachment_path=attachment_path,
                status="pending",  # Initial status
            )

            db.session.add(guideline_request)
            db.session.flush()  # Get the ID without committing

            # Try to send email
            email_sent = False
            try:
                email_sent = send_guideline_request_email(guideline_request)

                # Update status based on email success
                if email_sent:
                    guideline_request.status = (
                        "submitted"  # Change from 'pending' to 'submitted'
                    )
                    flash(
                        "Your guideline request has been submitted successfully! ",
                        "success",
                    )
                else:
                    guideline_request.status = "email_failed"
                    flash(
                        "Your request has been saved, but there was an issue sending the email notification.",
                        "warning",
                    )

            except Exception as e:
                current_app.logger.error(f"Email sending failed: {str(e)}")
                guideline_request.status = "email_failed"
                flash(
                    "Your request has been saved, but there was an issue sending the email notification.",
                    "warning",
                )

            # Commit all changes
            db.session.commit()

            return redirect(url_for("audit.my_guideline_requests"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error submitting guideline request: {str(e)}")
            flash(f"An error occurred: {str(e)}", "error")
            return render_template("request_guideline.html", form=form)

    return render_template("request_guideline.html", form=form)


@audit_bp.route("/api/guideline-requests/<int:request_id>", methods=["GET"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def get_guideline_request_details(request_id):
    """API endpoint to get guideline request details"""
    try:
        # Get the request with user and organization loaded
        guideline_request = (
            GuidelineRequest.query.options(
                db.joinedload(GuidelineRequest.user).joinedload(Users.organization)
            )
            .filter_by(id=request_id, user_id=current_user.id)
            .first()
        )

        if not guideline_request:
            return jsonify({"error": "Request not found or unauthorized"}), 404

        # Get attachment filename if exists
        attachment_filename = None
        if guideline_request.attachment_path:
            attachment_filename = os.path.basename(guideline_request.attachment_path)

        # Get organization name
        org_name = None
        if guideline_request.user.organization:
            org_name = guideline_request.user.organization.organization_name
        elif hasattr(guideline_request.user, "organization_name"):
            org_name = guideline_request.user.organization_name

        # Prepare response data
        response_data = {
            "id": guideline_request.id,
            "guideline_name": guideline_request.guideline_name,
            "regulator_name": guideline_request.regulator_name,
            "web_link": guideline_request.web_link,
            "attachment_filename": attachment_filename,
            "attachment_path": guideline_request.attachment_path,
            "status": guideline_request.status,
            "created_at": guideline_request.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": (
                guideline_request.updated_at.strftime("%Y-%m-%d %H:%M:%S")
                if guideline_request.updated_at
                else None
            ),
            "user_name": guideline_request.user.name,
            "user_email": guideline_request.user.email,
            "user_phone": guideline_request.user.phone_no,
            "organization": org_name,
        }

        return jsonify(response_data)

    except Exception as e:
        current_app.logger.error(
            f"Error fetching guideline request {request_id}: {str(e)}"
        )
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/my_guideline_requests", methods=["GET"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def my_guideline_requests():
    """Display user's guideline requests"""
    # Load requests with user relationship
    requests = (
        GuidelineRequest.query.filter_by(user_id=current_user.id)
        .options(db.joinedload(GuidelineRequest.user))
        .order_by(GuidelineRequest.created_at.desc())
        .all()
    )

    return render_template("my_guideline_requests.html", requests=requests)


@audit_bp.route("/api/guideline-requests/<int:request_id>", methods=["GET"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def get_guideline_request(request_id):
    """API endpoint to get guideline request details"""
    guideline_request = GuidelineRequest.query.get_or_404(request_id)

    # Check if current user owns this request
    if (
        guideline_request.user_id != current_user.id
        and current_user.role != "COMPLIFYRE"
    ):
        return jsonify({"error": "Unauthorized"}), 403

    return jsonify(guideline_request.to_dict())


@audit_bp.route("/my_guidelines", methods=["GET"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def my_guidelines():
    """
    This route returns guidelines selected by auditor
    """
    add_to_breadcrumb(request.full_path, "My Guidelines")

    # Debug: Check if current_user is available
    print(f"DEBUG: current_user type: {type(current_user)}")
    print(f"DEBUG: current_user.is_authenticated: {current_user.is_authenticated}")
    print(f"DEBUG: current_user.id: {getattr(current_user, 'id', 'No id')}")

    if current_user.is_authenticated:
        stmt = (
            select(Guidelines)
            .join(
                auditor_selected_guidelines,
                auditor_selected_guidelines.c.guideline_id == Guidelines.id,
            )
            .where(
                auditor_selected_guidelines.c.audit_id
                == current_user.auditor_profile_id
            )
        )

        result = db.session.execute(stmt).scalars().all()

        print(result)
        return render_template("my_guidelines.html", guidelines=result)

    else:
        flash("Please Login", "info")
        redirect("main.login")


@audit_bp.route("/add_my_guidelines", methods=["POST"])
def add_my_guidelines():
    """
    This route add guidelines to my guidelines
    """
    if current_user.is_authenticated:
        if current_user.auditor_profile_id:
            try:
                audit_id = current_user.auditor_profile_id
                guideline_id = request.form.get("guideline_id")
                audit = AuditOrganization.query.get(audit_id)
                guideline = Guidelines.query.get(guideline_id)
                audit.selected_guidelines.append(guideline)
                db.session.commit()
                flash("Added guideline to your instance", "success")
                return redirect(url_for("audit.my_guidelines"))
            except SQLAlchemyError:
                db.session.rollback()
                flash("Something went wrong, try again!", "warning")
                return redirect(request.referrer)
    else:
        flash("Please Login", "info")
        redirect("main.login")


@audit_bp.route("/create_organization", methods=["GET", "POST"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def create_organization_post():
    if request.method == "POST":
        try:
            firm_name = request.form.get("org_name", "").strip()
            firm_reg_no = request.form.get("org_reg_no", "").strip()
            firm_desc = request.form.get("description", "").strip()
            firm_address = request.form.get("address", "").strip()
            country = request.form.get("country", "").strip()
            state = request.form.get("state", "").strip()
            city = request.form.get("city", "").strip()
            num_emp = request.form.get("num_employees", "").strip()

            if not firm_name or not firm_reg_no:
                flash("Firm name and registration number are required.", "danger")
                return redirect(url_for("audit.create_organization"))

            names = request.form.getlist("name_person[]")
            emails = request.form.getlist("email_person[]")
            phones = request.form.getlist("phone_person[]")
            contacts = []
            for name, email, phone in zip(names, emails, phones):
                name, email, phone = name.strip(), email.strip(), phone.strip()
                if name or email or phone:
                    contacts.append({"name": name, "email": email, "phone": phone})

            # === STEP 1: Create BOTH AuditOrganization AND Organizations ===
            # Create AuditOrganization (your existing table)
            audit_org = AuditOrganization(
                firm_name=firm_name,
                firm_registration_no=firm_reg_no,
                firm_description=firm_desc,
                number_of_employees=num_emp,
            )
            db.session.add(audit_org)
            db.session.flush()  # Get audit_org.id
            print(f"✅ Created AuditOrganization with ID: {audit_org.id}")

            # Create Organizations table entry for foreign key relationship
            organization = Organizations(
                name=firm_name,
                legal_name=firm_name,  # Using same as name since you don't have separate field
                registration_number=firm_reg_no,
                status="active",
            )
            db.session.add(organization)
            db.session.flush()  # Get organization.organization_id
            print(f"✅ Created Organizations with ID: {organization.organization_id}")

            # === STEP 2: Process contact persons with credentials ===
            contact_credentials = []  # Store credentials for email sending

            for contact in contacts:
                if not contact["name"] or not contact["email"]:
                    continue  # Skip if name or email is missing

                # Check if contact already exists in OrganizationContacts
                existing_contact = OrganizationContacts.query.filter_by(
                    email=contact["email"]
                ).first()
                if existing_contact:
                    flash(
                        f"Contact with email {contact['email']} already exists. Please use a different email.",
                        "warning",
                    )
                    continue

                # Create contact in AuditOrgContactPerson (your existing table)
                audit_contact = AuditOrgContactPerson(
                    audit_org_id=audit_org.id,
                    name=contact["name"],
                    email=contact["email"],
                    phone=contact["phone"],
                )
                db.session.add(audit_contact)

                # Create OrganizationContacts
                org_contact = OrganizationContacts(
                    organization_id=organization.organization_id,
                    name=contact["name"],
                    email=contact["email"],
                    phone=contact["phone"],
                    contact_type="primary",
                )

                # Generate temporary password
                temp_password = org_contact.generate_temp_password()
                db.session.add(org_contact)
                db.session.flush()  # Get org_contact.contact_id
                print(
                    f"✅ Created OrganizationContact with ID: {org_contact.contact_id}"
                )

                # === CREATE USER RECORD FOR CONTACT PERSON ===
                # IMPORTANT: Use audit_org.id for auditor_profile_id (foreign key to AuditOrganization)
                print(f"🔄 Creating user account for: {contact['email']}")

                # Method 1: Try the main function first
                user = create_user_for_contact(
                    name=contact["name"],
                    email=contact["email"],
                    phone=contact["phone"],
                    temp_password=temp_password,
                    audit_org_id=audit_org.id,  # FIXED: Use audit_org.id instead of organization.organization_id
                )

                # If Method 1 fails due to session issues, recover the session
                if not user and db.session.is_active:
                    print("🔄 Recovering database session...")
                    try:
                        db.session.rollback()
                        # Re-add the objects that were rolled back
                        db.session.add(audit_org)
                        db.session.add(organization)
                        db.session.add(audit_contact)
                        db.session.add(org_contact)
                        db.session.flush()
                    except Exception as rollback_error:
                        print(f"❌ Session recovery failed: {str(rollback_error)}")

                # Method 2: If main function fails, try SQL approach
                if not user:
                    print("🔄 Trying SQL approach...")
                    user = create_user_direct_sql_fixed(
                        name=contact["name"],
                        email=contact["email"],
                        phone=contact["phone"],
                        temp_password=temp_password,
                        audit_org_id=audit_org.id,  # FIXED: Use audit_org.id instead of organization.organization_id
                    )

                # Method 3: If both methods fail, try manual creation
                if not user:
                    print("🔄 Trying manual object creation...")
                    try:
                        user = Users()
                        user.email = contact["email"]
                        user.name = contact["name"]
                        user.phone_no = contact["phone"]
                        user.role_id = 1  # Auditor role ID
                        user.auditor_profile_id = (
                            audit_org.id
                        )  # FIXED: Use audit_org.id instead of organization.organization_id
                        user.email_verified = True
                        user.status = "active"
                        user.tfa_enabled = True
                        user.set_password(temp_password)
                        user.session_token = secrets.token_urlsafe(24)

                        db.session.add(user)
                        print(
                            f"✅ Manual user creation successful for: {contact['email']}"
                        )
                    except Exception as manual_error:
                        print(f"❌ Manual creation also failed: {str(manual_error)}")
                        # Store the error but continue with other contacts
                        flash(
                            f"Failed to create user account for {contact['email']}. Contact support.",
                            "warning",
                        )

                # If user was created successfully, log it
                if user:
                    print(
                        f"✅ User record created for: {contact['name']} ({contact['email']})"
                    )
                else:
                    print(
                        f"❌ All user creation methods failed for: {contact['email']}"
                    )

                # Store credentials for email (regardless of user creation success)
                contact_credentials.append(
                    {
                        "name": contact["name"],
                        "email": contact["email"],
                        "temp_password": temp_password,
                    }
                )

            # === STEP 3: Create addresses ===
            if firm_address or country or state or city:
                # Create address in AuditOrgAddress (your existing table)
                audit_add_head = AuditOrgAddress(
                    audit_org_id=audit_org.id,
                    address=firm_address,
                    country=country,
                    state=state,
                    city=city,
                    head_office=True,
                )
                db.session.add(audit_add_head)

                # Also create address in OrganizationAddresses if needed
                org_address = OrganizationAddresses(
                    organization_id=organization.organization_id,
                    address_line1=firm_address,
                    country=country,
                    state=state,
                    city=city,
                    address_type="head_office",
                    is_primary=True,
                )
                db.session.add(org_address)
                print("✅ Created address records")

            # === STEP 4: Link current user to audit organization ===
            if current_user.is_authenticated:
                user = Users.query.filter_by(email=current_user.email).first()
                if user:
                    user.auditor_profile_id = audit_org.id
                    db.session.add(user)
                    print(
                        f"✅ Linked current user {user.email} to audit organization {audit_org.id}"
                    )

            # === STEP 5: Commit all changes ===
            db.session.commit()
            print("✅ All database changes committed successfully")

            # === STEP 6: Send emails after successful commit ===
            if contact_credentials:
                login_url = url_for("main.login", _external=True)
                email_sent_count = 0

                for credential in contact_credentials:
                    success = send_contact_credentials_email(
                        contact_email=credential["email"],
                        contact_name=credential["name"],
                        organization_name=firm_name,
                        login_url=login_url,
                        temp_password=credential["temp_password"],
                    )
                    if success:
                        email_sent_count += 1
                        print(f"✅ Email sent to: {credential['email']}")

                if email_sent_count > 0:
                    flash(
                        f"Auditing organization created successfully! Login credentials sent to {email_sent_count} contact person(s).",
                        "success",
                    )
                else:
                    flash(
                        "Auditing organization created successfully, but failed to send email credentials. Please contact support.",
                        "warning",
                    )
            else:
                flash("Auditing organization created successfully!", "success")

            # === STEP 7: DEBUG - Verify commit actually worked ===
            print("🔍 DEBUG - Verifying database commit...")
            for credential in contact_credentials:
                # Check if user actually exists in database
                user_check = Users.query.filter_by(email=credential["email"]).first()
                if user_check:
                    print(
                        f"✅ VERIFIED - User {credential['email']} exists in database with ID: {user_check.id}"
                    )
                else:
                    print(
                        f"❌ ALERT - User {credential['email']} NOT FOUND in database after commit!"
                    )

                # Check OrganizationContact
                org_contact_check = OrganizationContacts.query.filter_by(
                    email=credential["email"]
                ).first()
                if org_contact_check:
                    print(
                        f"✅ VERIFIED - OrganizationContact {credential['email']} exists with ID: {org_contact_check.contact_id}"
                    )
                else:
                    print(
                        f"❌ ALERT - OrganizationContact {credential['email']} NOT FOUND in database after commit!"
                    )

            return redirect(url_for("audit.my_guidelines"))

        except SQLAlchemyError as db_err:
            db.session.rollback()
            current_app.logger.error(f"Database error: {str(db_err)}")
            flash("A database error occurred.", "danger")
            return redirect(url_for("audit.create_organization"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Unexpected error: {str(e)}")
            flash("An unexpected error occurred.", "danger")
            return redirect(url_for("audit.create_organization"))

    add_to_breadcrumb(request.full_path, "Create Organization")
    return render_template("create_profile.html")


@audit_bp.route("/contact/dashboard")
@login_required
def contact_dashboard():
    """
    Dashboard for organization contacts after login
    """
    print(f"=== CONTACT DASHBOARD ACCESSED ===")
    print(f"Current user type: {type(current_user)}")
    print(f"Current user ID: {current_user.get_id()}")

    # Check if current user is an OrganizationContact
    if not hasattr(current_user, "contact_id"):
        print(f"User doesn't have contact_id attribute")
        print(
            f"Available attributes: {[attr for attr in dir(current_user) if not attr.startswith('_')]}"
        )
        flash("Access denied. This area is for organization contacts only.", "danger")
        return redirect(url_for("main.login"))

    print(f"Organization contact authenticated: {current_user.name}")
    print(f"Organization ID: {current_user.organization_id}")
    print(f"Contact ID: {current_user.contact_id}")

    # Get organization details
    organization = None

    # Try different organization models
    try:
        from app.models.organization import Organizations

        organization = Organizations.query.get(current_user.organization_id)
        if organization:
            print(f"Found in Organizations table: {organization}")
    except Exception as e:
        print(f"Error querying Organizations: {e}")

    if not organization:
        try:
            from app.models.auditOrganization import AuditOrganization

            organization = AuditOrganization.query.get(current_user.organization_id)
            if organization:
                print(f"Found in AuditOrganization table: {organization}")
        except Exception as e:
            print(f"Error querying AuditOrganization: {e}")

    if not organization:
        print("Organization not found in any table")
        flash("Organization not found. Please contact administrator.", "danger")
        return redirect(url_for("main.login"))

    print(f"Organization successfully loaded")

    return render_template(
        "audit_dash.html", organization=organization, contact=current_user
    )


@audit_bp.route("/projects/<int:org_id>", methods=["GET"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def get_projects(org_id):
    add_to_breadcrumb(request.full_path, "My Projects")
    try:
        projects = (
            db.session.query(Projects.project_name)
            .filter_by(client=org_id)
            .distinct()
            .all()
        )

        return render_template("project.html", projects=projects, org_id=org_id)
    except Exception as e:
        current_app.logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


@audit_bp.route("/create_project", methods=["GET"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def create_project():
    """
    Renders the project creation page for an authenticated auditor.

    This function fetches all necessary data to populate the 'create project'
    form. It retrieves only the guidelines specifically assigned to the
    logged-in auditor's firm, a list of all available departments, and a
    list of unique clients the auditor has previously worked with. It also
    constructs a mapping of guidelines to their associated compliance
    activities to dynamically populate the form.
    """
    add_to_breadcrumb(request.full_path, "Create Project")
    if current_user.is_authenticated and current_user.auditor_profile_id:
        auditor_id = current_user.auditor_profile_id
        try:
            org_id = request.args.get("org_id")
            guidelines_selected = request.args.getlist("guideline") or []
            # Get UNIQUE departments - FIXED
            departments = (
                db.session.query(OrganizationDepartments.department_name)
                .distinct()
                .order_by(OrganizationDepartments.department_name)
                .all()
            )

            # Convert to list of department names
            department_list = [
                dept[0] for dept in departments
            ]  # dept[0] because it's a tuple

            guidelines = (
                db.session.query(Guidelines)
                .join(auditor_selected_guidelines)
                .filter(auditor_selected_guidelines.c.audit_id == auditor_id)
                .options(
                    joinedload(Guidelines.clauses).joinedload(
                        Clauses.compliance_activities
                    )
                )
                .all()
            )

            all_projects = (
                db.session.query(Projects)
                .filter(Projects.auditing_firm == auditor_id)
                .distinct()
                .all()
            )
            query = (
                select(Organizations)
                .join(
                    auditor_client,
                    auditor_client.c.client_id == Organizations.organization_id,
                )
                .where(auditor_client.c.audit_id == auditor_id)
            )
            unique_clients = db.session.execute(query).scalars().all()

            org_profile_id = Organizations.query.filter_by(
                organization_id=org_id
            ).first()

            guideline_activity_map = {
                g.id: [
                    {
                        "id": a.id,
                        "description": a.activity_description,
                        "sub_process": a.sub_process,
                    }
                    for c in g.clauses
                    for a in c.compliance_activities
                ]
                for g in guidelines
            }

            location = db.session.scalars(
                select(OrganizationAddresses.city).where(
                    OrganizationAddresses.organization_id == org_id
                )
            ).all()

            return render_template(
                "create_project.html",
                guidelines=guidelines,
                selected_guidelines=guidelines_selected,
                departments=department_list,
                unique_clients=unique_clients,
                activity_map=guideline_activity_map,
                org_id=org_profile_id,
                location=location,
            )
        except Exception as e:
            current_app.logger.error(f"Unexpected error: {str(e)}")
            return jsonify({"error": "Internal server error"}), 500
    else:
        flash("Please Login", "warning")
        return redirect("main.login")


@audit_bp.route("/edit_project/<int:project_id>", methods=["GET"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def edit_project(project_id):
    """
    Renders the project edit page for an existing project.
    """
    add_to_breadcrumb(request.full_path, "Edit Project")
    if current_user.is_authenticated and current_user.auditor_profile_id:
        auditor_id = current_user.auditor_profile_id
        try:
            # Get the existing project with all relationships
            # Use subqueryload for departments if using lazy='dynamic'
            project = (
                Projects.query.filter_by(id=project_id, auditing_firm=auditor_id)
                .options(
                    joinedload(Projects.project_guidelines),
                    subqueryload(
                        Projects.departments
                    ),  # Use subqueryload instead of joinedload
                    joinedload(Projects.primary_department),
                )
                .first_or_404()
            )

            print(f"Editing project: {project.project_name}, ID: {project.id}")
            print(f"Project start date: {project.project_start_date}")
            print(
                f"Assessment start: {project.assesment_start_date}, end: {project.assesment_end_date}"
            )

            # Get all necessary data for the form
            department = OrganizationDepartments.query.all()
            department_names = {d.department_name for d in department}

            guidelines = (
                db.session.query(Guidelines)
                .join(auditor_selected_guidelines)
                .filter(auditor_selected_guidelines.c.audit_id == auditor_id)
                .options(
                    joinedload(Guidelines.clauses).joinedload(
                        Clauses.compliance_activities
                    )
                )
                .all()
            )

            # Get clients for dropdown
            query = (
                select(Organizations)
                .join(
                    auditor_client,
                    auditor_client.c.client_id == Organizations.organization_id,
                )
                .where(auditor_client.c.audit_id == auditor_id)
            )
            unique_clients = db.session.execute(query).scalars().all()

            # Get locations for the selected client
            location = db.session.scalars(
                select(OrganizationAddresses.city).where(
                    OrganizationAddresses.organization_id == project.client
                )
            ).all()

            # Get currently selected guidelines from project
            selected_guideline_ids = [
                str(pg.original_guideline_id) for pg in project.project_guidelines
            ]
            print(f"Selected guidelines: {selected_guideline_ids}")

            # Get currently selected departments
            selected_departments = []

            # If using dynamic relationship, use .all() to get the list
            if hasattr(project.departments, "all"):
                departments_list = project.departments.all()
                if departments_list:
                    selected_departments = [
                        dept.department_name for dept in departments_list
                    ]
            # Otherwise it's already a list
            elif project.departments:
                selected_departments = [
                    dept.department_name for dept in project.departments
                ]

            # Fallback to primary department
            if not selected_departments and project.primary_department:
                selected_departments = [project.primary_department.department_name]

            # Make sure we have unique department names
            selected_departments = list(set(selected_departments))
            print(f"Selected departments: {selected_departments}")

            # Get currently selected locations (adjust based on your model)
            selected_locations = []

            guideline_activity_map = {
                str(g.id): [
                    {
                        "id": a.id,
                        "description": a.activity_description,
                        "sub_process": a.sub_process,
                    }
                    for c in g.clauses
                    for a in c.compliance_activities
                ]
                for g in guidelines
            }

            # Format dates for the template
            project_start_date = (
                project.project_start_date.strftime("%Y-%m-%d")
                if project.project_start_date
                else ""
            )
            assessment_start_date = (
                project.assesment_start_date.strftime("%Y-%m-%d")
                if project.assesment_start_date
                else ""
            )
            assessment_end_date = (
                project.assesment_end_date.strftime("%Y-%m-%d")
                if project.assesment_end_date
                else ""
            )

            return render_template(
                "edit_project.html",
                project=project,
                guidelines=guidelines,
                selected_guidelines=selected_guideline_ids,
                departments=department_names,
                selected_departments=selected_departments,
                unique_clients=unique_clients,
                activity_map=guideline_activity_map,
                org_id=project.client,
                location=location,
                selected_locations=selected_locations,
                project_start_date=project_start_date,
                assessment_start_date=assessment_start_date,
                assessment_end_date=assessment_end_date,
            )
        except Exception as e:
            current_app.logger.error(f"Unexpected error in edit_project: {str(e)}")
            flash(f"Error loading project: {str(e)}", "error")
            return redirect(url_for("audit.my_projects"))
    else:
        flash("Please Login", "warning")
        return redirect(url_for("main.login"))


@audit_bp.route("/update_project/<int:project_id>", methods=["POST"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def update_project(project_id):
    """
    Updates an existing project.
    """
    try:
        firm_id = current_user.auditor_profile_id

        # Verify project exists and belongs to current auditor
        # Use subqueryload for departments
        project = (
            Projects.query.filter_by(id=project_id, auditing_firm=firm_id)
            .options(subqueryload(Projects.departments))
            .first_or_404()
        )

        data = request.form
        org_id = data.get("org_id")
        department_names = data.get("department", "")
        guideline_ids = data.get("guidelines", "")
        project_description = data.get("project_description")
        project_name = data.get("project_name")
        project_start_date = data.get("proj_start_date")
        assessment_start_date = data.get("assisment_start_date")
        assessment_end_date = data.get("assisment_end_date")

        print(f"Updating project {project_id}")
        print(f"Department names: {department_names}")
        print(f"Guideline IDs: {guideline_ids}")
        print(
            f"Dates - Start: {project_start_date}, Assessment: {assessment_start_date} to {assessment_end_date}"
        )

        # --- Update Basic Project Information ---
        project.client = org_id
        project.project_name = project_name
        project.project_description = project_description
        project.project_start_date = (
            datetime.strptime(project_start_date, "%Y-%m-%d")
            if project_start_date
            else None
        )
        project.assesment_start_date = (
            datetime.strptime(assessment_start_date, "%Y-%m-%d")
            if assessment_start_date
            else None
        )
        project.assesment_end_date = (
            datetime.strptime(assessment_end_date, "%Y-%m-%d")
            if assessment_end_date
            else None
        )

        # --- Update Departments (FIXED) ---
        department_list = [d.strip() for d in department_names.split(",") if d.strip()]

        # Clear existing departments
        if hasattr(project.departments, "all"):
            # For dynamic relationship
            existing_departments = list(project.departments)
            for dept in existing_departments:
                project.departments.remove(dept)
        elif project.departments:
            # For regular list relationship
            project.departments.clear()

        # Add new departments
        if department_list:
            department_records = OrganizationDepartments.query.filter(
                OrganizationDepartments.department_name.in_(department_list)
            ).all()

            for dept in department_records:
                project.departments.append(dept)

            # Also set primary department (first one)
            if department_records:
                project.primary_department_id = department_records[0].department_id
                print(f"Updated departments to: {department_list}")
        else:
            project.primary_department_id = None

        # --- Update Guidelines ---
        guideline_id_list = [
            int(g.strip()) for g in guideline_ids.split(",") if g.strip().isdigit()
        ]

        # Get current guideline IDs
        current_guideline_ids = {
            pg.original_guideline_id for pg in project.project_guidelines
        }
        new_guideline_ids = set(guideline_id_list)

        print(f"Current guidelines: {current_guideline_ids}")
        print(f"New guidelines: {new_guideline_ids}")

        # Remove guidelines that are no longer selected
        guidelines_to_remove = []
        for project_guideline in project.project_guidelines:
            if project_guideline.original_guideline_id not in new_guideline_ids:
                guidelines_to_remove.append(project_guideline)

        for guideline in guidelines_to_remove:
            db.session.delete(guideline)
            print(f"Removed guideline: {guideline.original_guideline_id}")

        # Add new guidelines
        for guideline_id in new_guideline_ids:
            if guideline_id not in current_guideline_ids:
                print(f"Adding new guideline: {guideline_id}")
                # Fetch the guideline template
                guideline_template = Guidelines.query.get(guideline_id)
                if guideline_template:
                    # Create new project guideline (reuse your creation logic)
                    project_guideline = ProjectGuideline(
                        original_guideline_id=guideline_template.id,
                        guideline_data=guideline_template.guideline_data,
                    )

                    # Build the complete structure
                    for clause_template in guideline_template.clauses:
                        project_clause = ProjectClause(
                            original_clause_id=clause_template.id,
                            clause_no=clause_template.clause_no,
                            clause_text=clause_template.clause_text,
                        )

                        for activity_template in clause_template.compliance_activities:
                            project_activity = ProjectComplianceActivity(
                                original_activity_id=activity_template.id,
                                activity_id=activity_template.activity_id,
                                activity_description=activity_template.activity_description,
                                responsible_party=activity_template.responsible_party,
                                frequency=activity_template.frequency,
                                evidence_required=activity_template.evidence_required,
                            )

                            # Add control activities, test procedures, etc. as needed
                            project_clause.project_compliance_activities.append(
                                project_activity
                            )

                        project_guideline.project_clauses.append(project_clause)

                    project.project_guidelines.append(project_guideline)

        # --- Save Changes ---
        db.session.commit()

        flash("Project updated successfully!", "success")
        return redirect(url_for("audit.my_projects", org_id=org_id))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating project: {str(e)}")
        flash(f"An error occurred while updating the project: {str(e)}", "error")
        return redirect(request.referrer or url_for("audit.dashboard"))


@audit_bp.route("/create_project", methods=["POST"])
def create_new_project():
    """
    Creates a new project and generates a complete, isolated instance of the
    audit structure (guidelines, clauses, activities, etc.) for that project.
    """
    try:
        # Check if free report was used
        if check_free_report_used():
            return redirect(url_for("audit.my_projects"))

        firm_id = current_user.auditor_profile_id
        data = request.form
        org_id = data.get("org_id")
        department_names = data.get("department", "")
        guideline_ids = data.get("guidelines", "")
        project_description = data.get("project_description")
        project_name = data.get("project_name")
        project_start_date = data.get("proj_start_date")
        assesment_start_date = data.get("assisment_start_date")
        assesment_end_date = data.get("assisment_end_date")

        # --- 1. Data Preparation ---
        department_list = [d.strip() for d in department_names.split(",") if d.strip()]
        guideline_id_list = [
            int(g.strip()) for g in guideline_ids.split(",") if g.strip().isdigit()
        ]

        # Get all department records
        department_records = OrganizationDepartments.query.filter(
            OrganizationDepartments.department_name.in_(department_list)
        ).all()

        if not department_records:
            flash("No valid departments were selected.", "error")
            return redirect(request.referrer)

        # Get primary department (first one in the list)
        primary_department = department_records[0] if department_records else None

        # --- 2. Create the Main Project Container ---
        new_project = Projects(
            auditing_firm=firm_id,
            client=org_id,
            project_name=project_name,
            project_description=project_description,
            primary_department_id=(
                primary_department.department_id if primary_department else None
            ),
            project_start_date=project_start_date,
            assesment_start_date=assesment_start_date,
            assesment_end_date=assesment_end_date,
        )

        # --- 3. Add departments to the many-to-many relationship ---
        # IMPORTANT: Add to session first before setting relationships
        db.session.add(new_project)
        db.session.flush()  # This assigns an ID to new_project

        # Now add the departments
        for dept in department_records:
            new_project.departments.append(dept)

        # --- 4. Fetch Master Guideline Templates ---
        guideline_templates = Guidelines.query.filter(
            Guidelines.id.in_(guideline_id_list)
        ).all()

        # --- 5. Build the Project Instance Tree ---
        for guideline_template in guideline_templates:
            project_guideline = ProjectGuideline(
                original_guideline_id=guideline_template.id,
                guideline_data=guideline_template.guideline_data,
            )

            for clause_template in guideline_template.clauses:
                project_clause = ProjectClause(
                    original_clause_id=clause_template.id,
                    clause_no=clause_template.clause_no,
                    clause_text=clause_template.clause_text,
                )

                for activity_template in clause_template.compliance_activities:
                    project_activity = ProjectComplianceActivity(
                        original_activity_id=activity_template.id,
                        activity_id=activity_template.activity_id,
                        activity_description=activity_template.activity_description,
                        responsible_party=activity_template.responsible_party,
                        frequency=activity_template.frequency,
                        evidence_required=activity_template.evidence_required,
                    )

                    for control_template in activity_template.control_activities:
                        project_control = ProjectControlActivity(
                            original_control_id=control_template.id,
                            activity_code=control_template.activity_code,
                            activity_name=control_template.activity_name,
                            activity_description=control_template.activity_description,
                            objective=control_template.objective,
                            owner=control_template.owner,
                            control_type=control_template.control_type,
                            frequency=control_template.frequency,
                            sampling_guidance=control_template.sampling_guidance,
                            explain_test_procedure=control_template.explain_test_procedure,
                        )

                        if control_template.test_procedure:
                            tp_template = control_template.test_procedure
                            project_tp = ProjectTestSteps(
                                original_test_steps_id=tp_template.id,
                                walkthrough=tp_template.walkthrough,
                                sampling=tp_template.sampling,
                            )

                            for doc_template in tp_template.documents:
                                project_doc = ProjectDocumentReview(
                                    original_document_review_id=doc_template.id,
                                    document_name=doc_template.document_name,
                                )
                                project_tp.project_documents.append(project_doc)

                            if tp_template.interviews:
                                interview_template = tp_template.interviews
                                project_interview = ProjectInterview(
                                    original_interview_id=interview_template.id
                                )

                                for role_template in interview_template.roles:
                                    project_role = ProjectInterviewRole(
                                        original_role_id=role_template.id,
                                        role=role_template.role,
                                    )
                                    project_interview.project_roles.append(project_role)

                                for q_template in interview_template.questions:
                                    project_q = ProjectInterviewQuestion(
                                        original_question_id=q_template.id,
                                        question=q_template.question,
                                    )
                                    project_interview.project_questions.append(
                                        project_q
                                    )

                                project_tp.project_interview = project_interview

                            project_control.project_test_procedure = project_tp

                        for evidence_template in control_template.evidences:
                            project_evidence = ProjectEvidenceArtifact(
                                original_evidence_id=evidence_template.id,
                                category=evidence_template.category,
                                item=evidence_template.item,
                            )
                            project_control.submitted_evidences.append(project_evidence)

                        project_activity.project_control_activities.append(
                            project_control
                        )

                    project_clause.project_compliance_activities.append(
                        project_activity
                    )

                project_guideline.project_clauses.append(project_clause)

            new_project.project_guidelines.append(project_guideline)

        # --- 6. Save to Database ---
        db.session.commit()

        print(
            f"Successfully created a new project with ID {new_project.id} and {len(department_records)} departments."
        )
        flash("Project created successfully!", "success")
        return redirect(url_for("audit.my_projects", org_id=org_id))

    except Exception as e:
        db.session.rollback()
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Project creation FULL ERROR: {str(e)}")
        logger.error(f"TRACEBACK: {error_details}")
        flash(
            f"Error: {str(e)}",
            "error",
        )
        return redirect(request.referrer or url_for("audit.dashboard"))


@audit_bp.route("/refetch_activities", methods=["POST"])
def refetch_project_activities():
    """
    Refetches and repopulates all compliance activities for a specific clause
    within an existing project. It first performs a targeted deletion of the old
    activities and their children (controls, test procedures, evidences, etc.)
    for the given clause, and then completely rebuilds them from the master
    templates.
    """
    try:
        project_id = request.form.get("project_id")
        # ID from the master 'Clauses' table (expects a single ID now)
        master_clause_id_str = request.form.get("master_clause_id")

        if not project_id or not master_clause_id_str:
            flash("Project ID and Clause ID are required.", "error")
            return redirect(request.referrer)

        master_clause_id = int(master_clause_id_str)

        # --- 1. Find the specific project clause that needs to be updated ---
        project_clause_to_update = ProjectClause.query.filter(
            ProjectClause.project_guideline.has(
                ProjectGuideline.project_id == project_id
            ),
            ProjectClause.original_clause_id == master_clause_id,
        ).first()

        if not project_clause_to_update:
            flash("No matching clause found in the project to update.", "warning")
            return redirect(request.referrer)

        # --- 2. Delete all existing compliance activities for this clause ---
        # Using synchronize_session='fetch' is safer with complex relationships.
        for act in ProjectComplianceActivity.query.filter_by(
            project_clause_id=project_clause_to_update.id
        ).all():
            db.session.delete(act)
        db.session.flush()
        # --- 3. Fetch Master Template for the clause and Re-populate ---
        clause_template = (
            Clauses.query.options(
                # Eagerly load all descendants to avoid multiple database hits
                joinedload(Clauses.compliance_activities)
                .joinedload(ComplianceActivities.control_activities)
                .joinedload(ControlActivity.evidences),
                joinedload(Clauses.compliance_activities)
                .joinedload(ComplianceActivities.control_activities)
                .joinedload(ControlActivity.test_procedure)
                .joinedload(TestSteps.documents),
                joinedload(Clauses.compliance_activities)
                .joinedload(ComplianceActivities.control_activities)
                .joinedload(ControlActivity.test_procedure)
                .joinedload(TestSteps.interviews)
                .joinedload(Interview.roles),
                joinedload(Clauses.compliance_activities)
                .joinedload(ComplianceActivities.control_activities)
                .joinedload(ControlActivity.test_procedure)
                .joinedload(TestSteps.interviews)
                .joinedload(Interview.questions),
            )
            .filter(Clauses.id == master_clause_id)
            .first()
        )

        if not clause_template:
            flash("Master clause template could not be found.", "error")
            return redirect(request.referrer)

        # --- 4. Rebuild the Full Activity Instance Tree (from create_project logic) ---
        for activity_template in clause_template.compliance_activities:
            project_activity = ProjectComplianceActivity(
                original_activity_id=activity_template.id,
                activity_id=activity_template.activity_id,
                activity_description=activity_template.activity_description,
                responsible_party=activity_template.responsible_party,
                frequency=activity_template.frequency,
                evidence_required=activity_template.evidence_required,
            )

            for control_template in activity_template.control_activities:
                project_control = ProjectControlActivity(
                    original_control_id=control_template.id,
                    activity_code=control_template.activity_code,
                    activity_name=control_template.activity_name,
                    activity_description=control_template.activity_description,
                    objective=control_template.objective,
                    owner=control_template.owner,
                    control_type=control_template.control_type,
                    frequency=control_template.frequency,
                    sampling_guidance=control_template.sampling_guidance,
                    explain_test_procedure=control_template.explain_test_procedure,
                assessment_objective=control_template.assessment_objective,
                assessment_objective_rationale=control_template.assessment_objective_rationale,
                test_attributes=control_template.test_attributes,
                )

                # Rebuild the Test Procedure if it exists
                if control_template.test_procedure:
                    tp_template = control_template.test_procedure
                    project_tp = ProjectTestSteps(
                        original_test_steps_id=tp_template.id,
                        walkthrough=tp_template.walkthrough,
                        sampling=tp_template.sampling,
                    )

                    for doc_template in tp_template.documents:
                        project_doc = ProjectDocumentReview(
                            original_document_review_id=doc_template.id,
                            document_name=doc_template.document_name,
                        )
                        project_tp.project_documents.append(project_doc)

                    if tp_template.interviews:
                        interview_template = tp_template.interviews
                        project_interview = ProjectInterview(
                            original_interview_id=interview_template.id
                        )

                        for role_template in interview_template.roles:
                            project_role = ProjectInterviewRole(
                                original_role_id=role_template.id,
                                role=role_template.role,
                            )
                            project_interview.project_roles.append(project_role)

                        for q_template in interview_template.questions:
                            project_q = ProjectInterviewQuestion(
                                original_question_id=q_template.id,
                                question=q_template.question,
                            )
                            project_interview.project_questions.append(project_q)

                        project_tp.project_interview = project_interview

                    project_control.project_test_procedure = project_tp

                # Rebuild the Evidence Artifacts
                for evidence_template in control_template.evidences:
                    project_evidence = ProjectEvidenceArtifact(
                        original_evidence_id=evidence_template.id,
                        category=evidence_template.category,
                        item=evidence_template.item,
                    )
                    project_control.submitted_evidences.append(project_evidence)

                project_activity.project_control_activities.append(project_control)

            project_clause_to_update.project_compliance_activities.append(
                project_activity
            )

        # --- 5. Save to Database ---
        db.session.commit()
        flash(
            f"Successfully refreshed activities for clause '{project_clause_to_update.clause_no}'.",
            "success",
        )

    except Exception as e:
        db.session.rollback()
        print(f"An error occurred while refetching activities: {e}")
        flash(
            "An error occurred while refetching activities. Please check the logs.",
            "error",
        )

    return redirect(request.referrer)


@audit_bp.route("/refetch_test_procedure", methods=["POST"])
def refetch_project_test_procedure():
    """
    Refetches and repopulates the test procedure for a single, specified
    control activity within an existing project. It first deletes the old test
    procedure and all its children, then rebuilds it from the master template.
    """
    try:
        project_control_id = request.form.get("project_control_activity_id")
        master_control_id = request.form.get("master_control_activity_id")
        parent_compliance_activity_id = request.form.get(
            "parent_compliance_activity_id"
        )

        if (
            not project_control_id
            or not master_control_id
            or not parent_compliance_activity_id
        ):
            flash(
                "Project Control ID, Master Control ID, and Parent Compliance Activity ID are required.",
                "error",
            )
            return redirect(
                request.referrer or url_for("audit_bp.refetch_project_test_procedure")
            )

        # --- 1. Find existing project control activity ---
        project_control = ProjectControlActivity.query.get(project_control_id)
        if not project_control:
            flash(
                "The specified control activity was not found in this project.", "error"
            )
            return redirect(
                request.referrer or url_for("audit_bp.refetch_project_test_procedure")
            )

        # --- 2. Fetch the Master Template ---
        control_template = ControlActivity.query.options(
            joinedload(ControlActivity.test_procedure).joinedload(TestSteps.documents),
            joinedload(ControlActivity.test_procedure)
            .joinedload(TestSteps.interviews)
            .joinedload(Interview.roles),
            joinedload(ControlActivity.test_procedure)
            .joinedload(TestSteps.interviews)
            .joinedload(Interview.questions),
            joinedload(ControlActivity.evidences),
        ).get(master_control_id)

        if not control_template:
            flash(
                "The master template for this control activity could not be found.",
                "error",
            )
            return redirect(
                request.referrer or url_for("audit_bp.refetch_project_test_procedure")
            )

        if not control_template.test_procedure:
            flash(
                "No test procedure exists in the master template for this control.",
                "warning",
            )
            return redirect(
                request.referrer or url_for("audit_bp.refetch_project_test_procedure")
            )

        # --- 3. Delete the existing project control activity ---
        db.session.delete(project_control)
        db.session.flush()  # ensures deletion is applied before inserting new one

        # --- 4. Rebuild the ProjectControlActivity ---
        new_project_control = ProjectControlActivity(
            project_compliance_activity_id=parent_compliance_activity_id,
            original_control_id=control_template.id,
            activity_code=control_template.activity_code,
            activity_name=control_template.activity_name,
            activity_description=control_template.activity_description,
            objective=control_template.objective,
            owner=control_template.owner,
            control_type=control_template.control_type,
            frequency=control_template.frequency,
            sampling_guidance=control_template.sampling_guidance,
            explain_test_procedure=control_template.explain_test_procedure,
            assessment_objective=control_template.assessment_objective,
            assessment_objective_rationale=control_template.assessment_objective_rationale,
            test_attributes=control_template.test_attributes,
        )

        # --- 4a. Rebuild Test Procedure ---
        tp_template = control_template.test_procedure
        project_tp = ProjectTestSteps(
            original_test_steps_id=tp_template.id,
            walkthrough=tp_template.walkthrough,
            sampling=tp_template.sampling,
        )

        # Copy documents
        for doc_template in tp_template.documents:
            project_doc = ProjectDocumentReview(
                original_document_review_id=doc_template.id,
                document_name=doc_template.document_name,
            )
            project_tp.project_documents.append(project_doc)

        # Copy interviews
        if tp_template.interviews:
            interview_template = tp_template.interviews
            project_interview = ProjectInterview(
                original_interview_id=interview_template.id
            )

            for role_template in interview_template.roles:
                project_role = ProjectInterviewRole(
                    original_role_id=role_template.id, role=role_template.role
                )
                project_interview.project_roles.append(project_role)

            for q_template in interview_template.questions:
                project_q = ProjectInterviewQuestion(
                    original_question_id=q_template.id, question=q_template.question
                )
                project_interview.project_questions.append(project_q)

            project_tp.project_interview = project_interview

        # Attach test procedure
        new_project_control.project_test_procedure = project_tp

        # --- 4b. Rebuild Evidences ---
        for evidence_template in control_template.evidences:
            project_evidence = ProjectEvidenceArtifact(
                original_evidence_id=evidence_template.id,
                category=evidence_template.category,
                item=evidence_template.item,
            )
            new_project_control.submitted_evidences.append(project_evidence)

        # --- 5. Save new ProjectControlActivity ---
        db.session.add(new_project_control)
        db.session.commit()

        flash("Successfully refreshed the test procedure.", "success")

    except Exception as e:
        db.session.rollback()
        print(f"An error occurred while refetching test procedures: {e}")
        flash(
            "An error occurred while refetching test procedures. Please check the logs.",
            "error",
        )

    return redirect(request.referrer)


# def test_procedures():
#     try:
#         pdf_service = PDFService()
#         data = request.get_json()
#         all_activities = data.get("activities", [])
#         print(all_activities)
#         for activity in all_activities:
#             print(activity)
#             clauses = Clauses.query.filter_by(id=activity.get('clause_id')).first()
#             print('clause',clauses)
#             if not clauses:
#                 continue
#             guideline_id = clauses.guideline_id
#             print('guideline_id',guideline_id)
#             if not guideline_id:
#                 continue
#             guideline = Guidelines.query.filter_by(id=guideline_id).first()
#             print('guide',guideline)
#             if not guideline:
#                 continue
#             file_url = File.query.filter_by(id=guideline.file_id).first()
#             print('file',file_url)
#             if not file_url:
#                 continue

#             url = file_url.path
#             text = pdf_service.extract_text_from_pdf(url)
#             json_data = pdf_service.test_procedures(clauses.clause_text, activity, text)
#             compliance_data = json.loads(f"""{json_data}""")

#             activity_data = TestProcedures(
#                 activity_id=activity.get("id"),
#                 data=compliance_data
#             )
#             db.session.add(activity_data)

#         db.session.commit()
#         return jsonify({"message": "All activity test procedure generated successfully."}), 200

#     except Exception as e:
#         db.session.rollback()
#         current_app.logger.error(f"Error generating all activity instructions: {str(e)}")
#         return jsonify({"message": "Error occurred during batch generation."}), 500


@audit_bp.route("/test_procedures", methods=["POST"])
def test_procedures():
    try:
        pdf_service = PDFService()
        data = request.get_json()
        all_activities = data.get("activities", [])
        # print(all_activities)
        for activity in all_activities:
            clauses = Clauses.query.filter_by(id=activity.get("clause_id")).first()
            print("clause", clauses)
            if not clauses:
                continue

            guideline_id = clauses.guideline_id
            guideline = (
                Guidelines.query.filter_by(id=guideline_id).first()
                if guideline_id
                else None
            )
            print(guideline)
            if not guideline:
                continue

            # file_url = File.query.filter_by(id=guideline.file_id).first()
            # print("file",file_url)
            # if not file_url:
            #     continue

            # url = file_url.path
            # PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

            # # Construct the full path
            # file_path = os.path.join(PROJECT_ROOT,url.strip('/'))
            # print("url",file_path)
            # text = pdf_service.extract_text_from_pdf(file_path)
            json_data = pdf_service.test_procedures(clauses.clause_text, activity, "")
            compliance_data = json.loads(json_data)

            # Save TestProcedures JSON (optional audit)
            activity_data = TestProcedures(
                activity_id=activity.get("id"), data=compliance_data
            )
            db.session.add(activity_data)

            # Create ControlActivity
            control = ControlActivity(
                activity_code=compliance_data.get("activity_code"),
                activity_name=compliance_data.get("activity_name"),
                activity_description=compliance_data.get("activity_description"),
                objective=compliance_data.get("objective"),
                owner=compliance_data.get("owner"),
                control_type=compliance_data.get("control_type"),
                frequency=compliance_data.get("frequency"),
                sampling_guidance=compliance_data.get("sampling_guidance"),
                auditor_observation=compliance_data.get("auditor_observation"),
                findings=compliance_data.get("findings"),
                impact=compliance_data.get("impact"),
                severity=compliance_data.get("severity"),
                recommendations=compliance_data.get("recommendations"),
                reviewer_notes=compliance_data.get("reviewer_notes"),
                compliance_activity_id=activity.get("id"),
                explain_test_procedure=activity.get("explain_test_procedure"),
            )
            db.session.add(control)
            db.session.flush()  # Ensure control.id is generated

            # Create TestSteps
            test_proc = TestSteps(
                walkthrough=compliance_data.get("test_procedure", {}).get(
                    "Walkthrough"
                ),
                sampling=compliance_data.get("test_procedure", {}).get("sampling"),
                control_id=control.id,
            )
            db.session.add(test_proc)
            db.session.flush()  # Ensure test_proc.id is available

            # Add Document Reviews
            for doc in compliance_data.get("test_procedure", {}).get(
                "review_of_documentation", []
            ):
                document_review = DocumentReview(
                    test_procedure_id=test_proc.id, document_name=doc
                )
                db.session.add(document_review)

            # Add Interviews
            interviews_data = compliance_data.get("test_procedure", {}).get(
                "interviews", {}
            )
            interview = Interview(test_procedure_id=test_proc.id)
            db.session.add(interview)
            db.session.flush()  # Ensure interview.id is generated

            for role in interviews_data.get("roles", []):
                db.session.add(InterviewRole(interview_id=interview.id, role=role))

            for question in interviews_data.get("key_questions", []):
                db.session.add(
                    InterviewQuestion(interview_id=interview.id, question=question)
                )

            # Add EvidenceArtifacts
            for category, items in compliance_data.get(
                "evidences_artifacts_needed", {}
            ).items():
                for item in items:
                    artifact = EvidenceArtifact.query.filter_by(
                        category=category, item=item
                    ).first()
                    if not artifact:
                        artifact = EvidenceArtifact(category=category, item=item)
                        db.session.add(artifact)
                        db.session.flush()
                    control.evidences.append(artifact)

        db.session.commit()
        return (
            jsonify(
                {
                    "message": "All activity test procedure generated and saved successfully."
                }
            ),
            200,
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error generating control activity data: {str(e)}")
        return jsonify({"message": "Error occurred during processing."}), 500


# @audit_bp.route('/test_evidence_artifacts/<int:activity_id>')
# def get_control_activity_data(activity_id):
#     try:
#         control = (
#             db.session.query(ControlActivity)
#             .filter_by(id=activity_id)
#             .options(
#                 db.joinedload(ControlActivity.test_procedure).joinedload(TestSteps.documents),
#                 db.joinedload(ControlActivity.test_procedure).joinedload(TestSteps.interviews).joinedload(Interview.roles),
#                 db.joinedload(ControlActivity.test_procedure).joinedload(TestSteps.interviews).joinedload(Interview.questions),
#                 db.joinedload(ControlActivity.evidences)
#             )
#             .first()
#         )

#         if not control:
#             return None

#         test_procedure = control.test_procedure
#         interview_obj = test_procedure.interviews if test_procedure else None

#         document_reviews = [doc.document_name for doc in test_procedure.documents] if test_procedure else []

#         interview_data = {
#             "roles": [role.role for role in interview_obj.roles] if interview_obj else [],
#             "questions": [
#                 {"question": q.question, "answer": q.answer}
#                 for q in interview_obj.questions
#             ] if interview_obj else []
#         }

#         evidence_data = {}
#         for evidence in control.evidences:
#             evidence_data.setdefault(evidence.category, []).append(evidence.item)

#         response = {
#             "activity_code": control.activity_code,
#             "activity_name": control.activity_name,
#             "activity_description": control.activity_description,
#             "objective": control.objective,
#             "owner": control.owner,
#             "control_type": control.control_type,
#             "frequency": control.frequency,
#             "sampling_guidance": control.sampling_guidance,
#             "auditor_observation": control.auditor_observation,
#             "findings": control.findings,
#             "impact": control.impact,
#             "severity": control.severity,
#             "recommendations": control.recommendations,
#             "reviewer_notes": control.reviewer_notes,
#             "test_procedure": {
#                 "Walkthrough": test_procedure.walkthrough if test_procedure else None,
#                 "sampling": test_procedure.sampling if test_procedure else None,
#                 "review_of_documentation": document_reviews,
#                 "interviews": interview_data,
#             },
#             "evidences_artifacts_needed": evidence_data
#         }

#         return response

#     except Exception as e:
#         current_app.logger.error(f"Error fetching control activity data: {str(e)}")
#         return None


# def get_all_control_activities_by_compliance(compliance_id):
#     try:
#         control_activities = (
#             db.session.query(ControlActivity)
#             .filter_by(compliance_activity_id=compliance_id)
#             .options(
#                 db.joinedload(ControlActivity.test_procedure).joinedload(TestSteps.documents),
#                 db.joinedload(ControlActivity.test_procedure).joinedload(TestSteps.interviews).joinedload(Interview.roles),
#                 db.joinedload(ControlActivity.test_procedure).joinedload(TestSteps.interviews).joinedload(Interview.questions),
#                 db.joinedload(ControlActivity.evidences)
#             )
#             .all()
#         )

#         result = []
#         for control in control_activities:
#             # Reuse loaded `control` object
#             result.append(get_control_activity_data(control.id))

#         return result

#     except Exception as e:
#         current_app.logger.error(f"Error fetching control activities for compliance ID {compliance_id}: {str(e)}")
#         return []


@audit_bp.route("/submit_interview_answer", methods=["POST"])
def submit_interview_answer():
    """
    Saves the answer for a specific project's interview question.
    """
    try:
        project_question_id = request.form.get("question_id")
        answer = request.form.get("answer")

        if not project_question_id or not answer:
            return (
                jsonify({"success": False, "error": "Missing question ID or answer"}),
                400,
            )

        project_question = ProjectInterviewQuestion.query.get(project_question_id)
        if not project_question:
            return (
                jsonify(
                    {"success": False, "error": "Project interview question not found"}
                ),
                404,
            )

        project_question.answer = answer
        db.session.commit()

        flash("Answer updated successfully!", "success")
        return redirect(request.referrer or url_for("audit.dashboard"))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating interview answer: {str(e)}")
        flash("An error occurred while saving the answer.", "danger")
        return redirect(request.referrer or url_for("audit.dashboard"))


@audit_bp.route("/update_control_activity", methods=["POST"])
def update_control_activity():
    """
    Updates the status, findings, and recommendations for a specific
    project control activity based on auditor input.
    """
    try:
        project_control_activity_id = request.form.get("activity_id")
        compliant_status = request.form.get("compliant_status", "").strip().lower()
        control_findings = request.form.get("findings_content", "").strip()
        control_recommendation = request.form.get("recommendation_content", "").strip()

        if not project_control_activity_id or not compliant_status:
            flash("Activity ID and Compliance Status are required.", "warning")
            return redirect(request.referrer)

        project_control_activity = ProjectControlActivity.query.get(
            project_control_activity_id
        )

        if not project_control_activity:
            flash("Project control activity not found.", "danger")
            return redirect(request.referrer)

        project_control_activity.compliant_status = compliant_status
        if compliant_status in ["partially-compliant", "not-compliant"]:
            project_control_activity.control_findings = control_findings
            project_control_activity.control_recommendation = control_recommendation
        else:
            project_control_activity.control_findings = None
            project_control_activity.control_recommendation = None

        db.session.commit()
        flash("Control activity updated successfully!", "success")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating control activity: {str(e)}")
        flash("An error occurred while updating the control activity.", "danger")

    return redirect(request.referrer)


@audit_bp.route("/answer_question_from_mom", methods=["POST"])
def answer_question_from_mom():
    """
    Handles the POST request to answer questions from a Minute of Meeting (MOM) document.
    Extracts content from the uploaded MOM, generates answers using an AI model,
    and updates the project-specific interview question records in the database.
    """
    try:
        if "minute_of_meeting" not in request.files:
            flash("No file part in the request.", "danger")
            return redirect(request.referrer)

        files = request.files["minute_of_meeting"]

        if not files or files.filename == "":
            flash("No selected file.", "danger")
            return redirect(request.referrer)

        # if not allowed_file(files.filename):
        #     flash("Invalid file type.", "danger")
        #     return redirect(request.referrer)

        filename = secure_filename(files.filename)
        # Assuming UPLOAD_FOLDER is defined globally
        # file_path = os.path.join(UPLOAD_FOLDER_MOM, filename)
        # os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        full_physical_file_path = None
        filename = ""
        if files and files.filename:
            if files.filename:
                filename = secure_filename(
                    f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{files.filename}"
                )
                full_physical_file_path = os.path.join(UPLOAD_FOLDER_MOM, filename)
                try:
                    files.save(full_physical_file_path)
                except IOError as io_err:
                    flash(f"Error saving file: {io_err}", "danger")
                    return redirect(request.referrer)
            # else:
            #     flash("Invalid file type.", "warning")
            #     return redirect(request.referrer)

        # try:
        #     files.save(full_physical_file_path)
        # except IOError as io_err:
        #     flash(f"Error saving file: {io_err}", "danger")
        #     return redirect(request.referrer)

        content = ""
        try:
            content = extract_content(full_physical_file_path)
            if not content:
                flash("Could not extract content from the document.", "warning")
                return redirect(request.referrer)
        except Exception as e:
            flash(f"Error extracting content: {e}", "danger")
            return redirect(request.referrer)

        file_extensions_to_exclude = (".docx", ".doc", ".pdf")
        vector_info = None
        file_info = None
        if full_physical_file_path.endswith(file_extensions_to_exclude):
            vector_info = create_vector_store(filename)
            file_upload_openai = upload_single_file(
                full_physical_file_path, vector_info.get("id")
            )
            file_info = file_upload_openai
            print("Here it is in function", file_info)
            if (
                not isinstance(file_upload_openai, dict)
                or file_upload_openai.get("status") != "success"
            ):
                logger.error("Vector store upload failed: %s", file_upload_openai)
                return {
                    "status": "error",
                    "message": "File upload to vector store failed",
                }

        questions_processed = False
        for key, value in request.form.items():
            if "question_id" in key and value.isdigit():
                project_question_id = int(value)

                # --- CORE CHANGE: Query the project-specific table ---
                get_question = ProjectInterviewQuestion.query.get(project_question_id)

                if get_question:
                    questions_processed = True
                    try:
                        prompt = get_compliance_prompt(
                            project_question_id, get_question.question
                        )
                        # prompt = prompt_get_answer(project_question_id, get_question.question, content)
                        res = extract_structured_info_3(
                            prompt,
                            ComplianceQuestion,
                            full_physical_file_path,
                            vector_info.get("id") if vector_info else None,
                        )
                        # res = generate_chat_output(prompt)

                        try:
                            ai_answer = res.answer
                            if ai_answer:
                                get_question.answer = ai_answer
                            else:
                                flash(
                                    f"AI response for question ID {project_question_id} was empty.",
                                    "warning",
                                )
                        except (json.JSONDecodeError, AttributeError):
                            flash(
                                f"Failed to parse AI response for question ID {project_question_id}.",
                                "warning",
                            )
                        except Exception as ai_e:
                            flash(
                                f"Error processing AI answer for question ID {project_question_id}: {ai_e}",
                                "warning",
                            )

                    except Exception as e:
                        flash(
                            f"Error generating answer for question ID {project_question_id}: {e}",
                            "danger",
                        )
                else:
                    flash(f"Project question with ID {value} not found.", "warning")

        if not questions_processed:
            flash("No valid questions were submitted for answering.", "info")
            return redirect(request.referrer)

        db.session.commit()
        if vector_info and file_info:
            delete_vector_store(vector_info.get("id"))
            delete_file(file_info.get("file_id"))
        flash("Answered Questions Successfully!", "success")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in answer_question_from_mom: {str(e)}")
        flash(f"An unexpected error occurred: {e}", "danger")

    return redirect(request.referrer)


# Helper function for allowed file types (add this to your utils or a separate config)
def allowed_file(filename):
    """Checks if the uploaded file has an allowed extension."""
    ALLOWED_EXTENSIONS = {
        "pdf",
        "png",
        "jpg",
        "jpeg",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "ppt",
        "pptx",
        "csv",
        "txt",
        "mp3",
        "wav",
    }

    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@audit_bp.route("/add_interview_question", methods=["POST"])
def add_interview_question():
    """
    Adds a new, custom interview question to a specific project control activity.
    If the necessary parent records (Test Procedure, Interview) do not exist
    for the project instance, they are created on-the-fly.
    """
    try:
        project_control_activity_id = request.form.get("activity_id")
        question_text = request.form.get("question")

        if not project_control_activity_id or not question_text:
            flash("Activity ID and question text are required.", "danger")
            return redirect(request.referrer)

        project_control_activity = ProjectControlActivity.query.get(
            project_control_activity_id
        )
        if not project_control_activity:
            flash("Project Control Activity not found.", "danger")
            return redirect(request.referrer)

        project_test_procedure = project_control_activity.project_test_procedure
        if not project_test_procedure:
            project_test_procedure = ProjectTestSteps(
                project_control_activity_id=project_control_activity.id
            )
            db.session.add(project_test_procedure)
            db.session.flush()

        project_interview = project_test_procedure.project_interview
        if not project_interview:
            project_interview = ProjectInterview(
                project_test_procedure_id=project_test_procedure.id
            )
            db.session.add(project_interview)
            db.session.flush()

        new_question = ProjectInterviewQuestion(
            project_interview_id=project_interview.id, question=question_text
        )
        db.session.add(new_question)
        db.session.commit()

        flash("New interview question added successfully!", "success")

        redirect_url = (
            f"{request.referrer.split('?')[0]}?new_question_id={new_question.id}"
        )
        return redirect(redirect_url)

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error adding interview question: {str(e)}")
        flash("An error occurred while adding the question.", "danger")
        return redirect(request.referrer)


@audit_bp.route("/submit-other-evidence", methods=["POST"])
def new_evidances():
    """
    Adds a new, custom evidence artifact to a specific project control activity.
    """
    try:
        category = request.form.get("category")
        item = request.form.get("item")
        project_control_activity_id = request.form.get("control_id")

        if not project_control_activity_id:
            flash("Control ID is missing!", "error")
            return redirect(request.referrer)

        if not category or not item:
            flash("Category and Item are required for new evidence.", "error")
            return redirect(request.referrer)

        project_control = ProjectControlActivity.query.get(project_control_activity_id)
        if not project_control:
            flash("Project Control Activity not found!", "error")
            return redirect(request.referrer)

        new_artifact = ProjectEvidenceArtifact(
            category=category, item=item, project_control_activity_id=project_control.id
        )

        db.session.add(new_artifact)
        db.session.commit()

        flash("New evidence requirement added successfully!", "success")
        return redirect(request.referrer)

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error adding new evidence: {str(e)}")
        flash(f"An error occurred: {str(e)}", "error")
        return redirect(request.referrer)


@audit_bp.route("/consolidate_evidence", methods=["POST"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def consolidate_evidence():
    """
    Fetch consolidated evidence from complifyre instance for selected clauses
    """
    try:
        project_name = request.form.get("project_name")
        if not project_name:
            flash("Project name is missing.", "danger")
            return redirect(request.referrer)

        project = Projects.query.filter_by(project_name=project_name).first()
        if not project:
            flash(f"Project with name {project_name} not found.", "danger")
            return redirect(request.referrer)

        # Get all applicable clauses for this project
        applicable_clauses = []
        guideline_clause_map = {}  # Map guideline_id to clause_nos

        for p_guideline in project.project_guidelines:
            # FIX: Use original_guideline_id from ProjectGuideline model
            guideline_id = p_guideline.original_guideline_id

            if not guideline_id:
                current_app.logger.warning(
                    f"Could not find original_guideline_id for ProjectGuideline {p_guideline.id}"
                )
                continue

            guideline_clause_map[guideline_id] = []

            for p_clause in p_guideline.project_clauses:
                if p_clause.applicability:  # Only applicable clauses
                    applicable_clauses.append(
                        {
                            "guideline_id": guideline_id,
                            "clause_no": p_clause.clause_no,
                            "clause_id": p_clause.id,
                        }
                    )
                    guideline_clause_map[guideline_id].append(p_clause.clause_no)

        if not applicable_clauses:
            flash("No applicable clauses selected for this project.", "info")
            return redirect(request.referrer)

        current_app.logger.info(
            f"Processing {len(applicable_clauses)} applicable clauses for project {project_name}"
        )
        current_app.logger.info(
            f"Guideline IDs with clauses: {list(guideline_clause_map.keys())}"
        )

        # Fetch consolidated evidence from complifyre for each guideline
        all_consolidated_evidence = []

        for guideline_id, clause_nos in guideline_clause_map.items():
            if clause_nos:
                current_app.logger.info(
                    f"Fetching evidence for guideline {guideline_id}, clauses: {clause_nos}"
                )
                complifyre_evidence = fetch_complifyre_evidence_for_guideline(
                    guideline_id, clause_nos
                )
                if complifyre_evidence:
                    all_consolidated_evidence.extend(complifyre_evidence)

        if not all_consolidated_evidence:
            flash("No consolidated evidence found for the selected clauses.", "info")
            return redirect(request.referrer)

        # Save to database
        final_output = {"grouped_evidences": all_consolidated_evidence}

        evidence_record = ConsolidatedEvidence.query.filter_by(
            project_id=project_name
        ).first()

        if evidence_record:
            evidence_record.consolidate_evidence = final_output
        else:
            evidence_record = ConsolidatedEvidence(
                project_id=project_name, consolidate_evidence=final_output
            )
            db.session.add(evidence_record)

        db.session.commit()

        # Calculate statistics
        total_clauses = len(applicable_clauses)
        evidence_groups = len(all_consolidated_evidence)

        flash(
            f"Evidence consolidated successfully! Fetched {evidence_groups} evidence groups for {total_clauses} applicable clauses.",
            "success",
        )

        # Log success
        current_app.logger.info(
            f"Successfully consolidated evidence for project {project_name}"
        )

    except Exception as err:
        db.session.rollback()
        current_app.logger.error(
            f"Unexpected error in consolidate_evidence: {str(err)}", exc_info=True
        )
        flash("An internal server error occurred.", "danger")

    return redirect(request.referrer)


def fetch_complifyre_evidence_for_guideline(guideline_id, applicable_clause_nos):
    """
    Fetch and filter complifyre consolidated evidence for specific clauses
    """
    try:
        # Query the complifyre consolidated evidence table
        complifyre_evidence = ComplifyreConsolidatedEvidence.query.filter_by(
            guideline_id=guideline_id
        ).first()

        if not complifyre_evidence or not complifyre_evidence.consolidate_evidence:
            current_app.logger.info(
                f"No consolidated evidence found for guideline {guideline_id}"
            )
            return []

        # Parse the evidence data
        if isinstance(complifyre_evidence.consolidate_evidence, str):
            evidence_data = json.loads(complifyre_evidence.consolidate_evidence)
        else:
            evidence_data = complifyre_evidence.consolidate_evidence

        grouped_evidences = evidence_data.get("grouped_evidences", [])
        if not grouped_evidences:
            return []

        # Filter evidence groups to only include applicable clauses
        filtered_evidence = []
        applicable_clause_set = set(applicable_clause_nos)

        for evidence_group in grouped_evidences:
            if not isinstance(evidence_group, dict):
                continue

            required_by = evidence_group.get("required_by", {})
            if not isinstance(required_by, dict):
                continue

            # Get clause numbers from this evidence group
            evidence_clause_nos = set(required_by.get("clause_nos", []))

            # Find intersection with applicable clauses
            relevant_clauses = evidence_clause_nos.intersection(applicable_clause_set)

            if relevant_clauses:
                # Create a filtered copy of the evidence group
                filtered_group = evidence_group.copy()
                filtered_group["required_by"] = required_by.copy()
                filtered_group["required_by"]["clause_nos"] = list(relevant_clauses)

                # Also filter activity_ids and guideline_ids if needed
                # (You might want to add similar filtering for these based on your project structure)

                filtered_evidence.append(filtered_group)

        current_app.logger.info(
            f"Filtered {len(filtered_evidence)} evidence groups from {len(grouped_evidences)} "
            f"for guideline {guideline_id}, clauses {applicable_clause_nos}"
        )

        return filtered_evidence

    except Exception as e:
        current_app.logger.error(
            f"Error fetching complifyre evidence for guideline {guideline_id}: {str(e)}"
        )
        return []


@audit_bp.route("/debug-redis")
def debug_redis():
    """Debug Redis connection"""
    try:
        redis_conn = get_redis_connection()
        # Test basic operations
        test_key = f"debug_test_{datetime.now().timestamp()}"
        redis_conn.setex(test_key, 30, "test_value")
        value = redis_conn.get(test_key)
        redis_conn.delete(test_key)

        if value == "test_value":
            return jsonify(
                {
                    "status": "SUCCESS",
                    "message": "Redis connection is working correctly",
                }
            )
        else:
            return jsonify(
                {"status": "FAILED", "message": f"Redis returned wrong value: {value}"}
            )
    except Exception as e:
        return (
            jsonify(
                {"status": "ERROR", "message": f"Redis connection failed: {str(e)}"}
            ),
            500,
        )


@audit_bp.route("/evidence-consolidation-progress/<task_id>")
def evidence_consolidation_progress(task_id):
    """SSE endpoint for evidence consolidation progress."""

    def generate():
        redis_conn = get_redis_connection()
        last_progress = -1

        logger.info(f"Starting SSE for task {task_id}")

        while True:
            try:
                progress_data = redis_conn.get(f"evidence_progress:{task_id}")

                if progress_data:
                    data = json.loads(progress_data)
                    current_progress = data.get("progress", 0)
                    current_status = data.get("status", "UNKNOWN")

                    # Send update if progress changed or status is terminal
                    if current_progress != last_progress or current_status in [
                        "COMPLETED",
                        "FAILED",
                        "ERROR",
                    ]:

                        yield f"data: {json.dumps(data)}\n\n"
                        last_progress = current_progress

                        # Stop if task completed
                        if current_status in ["COMPLETED", "FAILED", "ERROR"]:
                            logger.info(f"Task {task_id} finished: {current_status}")
                            break

                time.sleep(2)  # Check every 2 seconds

            except Exception as e:
                logger.error(f"SSE Error: {str(e)}")
                error_data = {
                    "status": "ERROR",
                    "progress": 0,
                    "message": f"Progress monitoring error: {str(e)}",
                }
                yield f"data: {json.dumps(error_data)}\n\n"
                time.sleep(5)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@audit_bp.route("/api/task-progress/<task_id>")
def api_task_progress(task_id):
    """API endpoint for polling task progress."""
    try:
        redis_conn = get_redis_connection()
        progress_data = redis_conn.get(f"evidence_progress:{task_id}")

        if progress_data:
            return jsonify(json.loads(progress_data))
        else:
            return (
                jsonify(
                    {
                        "status": "PENDING",
                        "progress": 0,
                        "message": "Task not found or expired",
                    }
                ),
                404,
            )

    except Exception as e:
        logger.error(f"Task progress error: {str(e)}")
        return (
            jsonify(
                {
                    "status": "ERROR",
                    "progress": 0,
                    "message": f"Error fetching progress: {str(e)}",
                }
            ),
            500,
        )


@audit_bp.route("/debug-config")
def debug_config():
    """Debug configuration settings."""
    config = {
        "REDIS_HOST": current_app.config.get("REDIS_HOST"),
        "REDIS_PORT": current_app.config.get("REDIS_PORT"),
        "REDIS_PASSWORD": "***" if current_app.config.get("REDIS_PASSWORD") else None,
        "CELERY_REDIS_DB": current_app.config.get("CELERY_REDIS_DB"),
        "DEBUG": current_app.config.get("DEBUG"),
    }
    return jsonify(config)


@audit_bp.route("/complifyre_consolidate_evidence", methods=["POST"])
def complifyre_consolidate_evidence():
    """Start evidence consolidation as a Celery task."""
    try:
        guideline_id = request.form.get("guideline_id")
        if not guideline_id:
            flash("Guideline ID is missing.", "danger")
            return redirect(request.referrer)

        guideline = Guidelines.query.get(guideline_id)
        if not guideline:
            flash(f"Guideline with ID {guideline_id} not found.", "danger")
            return redirect(request.referrer)

        # Get the current user's ID
        user_id = current_user.id if current_user.is_authenticated else None

        # Start the celery task
        task = consolidate_evidence_task.delay(int(guideline_id), user_id)

        # Store initial task status
        task_status = TaskStatus()
        task_status.set_status(
            task_id=task.id,
            user_id=user_id,
            task_name="consolidate_evidence",
            status="pending",
            progress=0,
            message="Task queued",
        )

        flash("Evidence consolidation started. Please wait for completion.", "info")
        return _json_response(
            "success", "Evidence consolidation started.", 202, task_id=task.id
        )

    except Exception as err:
        logger.error(
            f"Error starting evidence consolidation: {str(err)}", exc_info=True
        )
        flash("An error occurred while starting evidence consolidation.", "danger")
        return redirect(request.referrer)


def create_fallback_evidence(clauses, guideline_id):
    """Create a basic evidence structure when AI service fails."""
    grouped_evidences = []

    for clause in clauses:
        evidence_group = {
            "evidence_item_name": f"Compliance Evidence for Clause {clause.clause_no}",
            "required_by": {
                "guideline_ids": [str(guideline_id)],
                "clause_nos": [clause.clause_no],
                "activity_ids": [],
                "evidence": [
                    {
                        "evidence_id": None,
                        "evidence_item": f"Manual evidence required for clause {clause.clause_no}",
                    }
                ],
            },
        }

        # Add activity IDs if they exist
        if clause.compliance_activities:
            for activity in clause.compliance_activities:
                evidence_group["required_by"]["activity_ids"].append(str(activity.id))

        grouped_evidences.append(evidence_group)

    return {"grouped_evidences": grouped_evidences}


def process_clauses_chunk(clauses, guideline_id):
    """Process a chunk of clauses and extract evidence items."""
    evidence_items = []

    for clause in clauses:
        current_app.logger.info(f"Processing clause: {clause.clause_no}")
        clause_included = False

        # Check if this clause has compliance activities
        if clause.compliance_activities:
            for activity in clause.compliance_activities:
                # Check if this activity has control activities
                if activity.control_activities:
                    for control in activity.control_activities:
                        # Check if this control has evidences
                        if control.evidences:
                            for evidence in control.evidences:
                                evidence_items.append(
                                    {
                                        "guideline_id": str(guideline_id),
                                        "clause_id": str(clause.id),
                                        "clause_no": clause.clause_no,
                                        "activity_id": str(activity.id),
                                        "control_id": str(control.id),
                                        "evidence_id": str(evidence.id),
                                        "evidence_item": evidence.item,
                                        "has_evidence": True,
                                        "level": "evidence",
                                    }
                                )
                                clause_included = True
                        else:
                            # Include control activities without evidence
                            evidence_items.append(
                                {
                                    "guideline_id": str(guideline_id),
                                    "clause_id": str(clause.id),
                                    "clause_no": clause.clause_no,
                                    "activity_id": str(activity.id),
                                    "control_id": str(control.id),
                                    "evidence_id": None,
                                    "evidence_item": f"Control: {control.activity_code or control.activity_name} (No evidence submitted)",
                                    "has_evidence": False,
                                    "level": "control",
                                }
                            )
                            clause_included = True
                else:
                    # Include compliance activities without control activities
                    evidence_items.append(
                        {
                            "guideline_id": str(guideline_id),
                            "clause_id": str(clause.id),
                            "clause_no": clause.clause_no,
                            "activity_id": str(activity.id),
                            "control_id": None,
                            "evidence_id": None,
                            "evidence_item": f"Activity: {activity.activity_id} (No control activities)",
                            "has_evidence": False,
                            "level": "activity",
                        }
                    )
                    clause_included = True
        else:
            # Include clauses without any compliance activities
            evidence_items.append(
                {
                    "guideline_id": str(guideline_id),
                    "clause_id": str(clause.id),
                    "clause_no": clause.clause_no,
                    "activity_id": None,
                    "control_id": None,
                    "evidence_id": None,
                    "evidence_item": f"Clause: {clause.clause_no} (No compliance activities)",
                    "has_evidence": False,
                    "level": "clause",
                }
            )
            clause_included = True

    return evidence_items


def merge_evidence_groups(evidence_groups):
    """Merge similar evidence groups from different chunks with proper error handling."""
    if not evidence_groups:
        return []

    merged_evidence = {}

    for i, group in enumerate(evidence_groups):
        try:
            # Skip if group is not a dictionary
            if not isinstance(group, dict):
                current_app.logger.warning(
                    f"Skipping group {i}: not a dictionary, type: {type(group)}"
                )
                continue

            evidence_name = group.get("evidence_item_name", "").lower().strip()
            if not evidence_name:
                current_app.logger.warning(
                    f"Skipping group {i}: missing evidence_item_name"
                )
                continue

            required_by = group.get("required_by", {})
            if not isinstance(required_by, dict):
                current_app.logger.warning(
                    f"Skipping group {i}: required_by is not a dictionary"
                )
                continue

            if evidence_name not in merged_evidence:
                # New evidence type, add it directly
                merged_evidence[evidence_name] = group
            else:
                # Merge with existing evidence type
                existing = merged_evidence[evidence_name]

                # Ensure existing has the required structure
                if "required_by" not in existing or not isinstance(
                    existing["required_by"], dict
                ):
                    current_app.logger.warning(
                        f"Existing group for {evidence_name} has invalid structure, replacing"
                    )
                    merged_evidence[evidence_name] = group
                    continue

                # Merge guideline_ids
                existing_guidelines = set(
                    existing["required_by"].get("guideline_ids", [])
                )
                new_guidelines = set(required_by.get("guideline_ids", []))
                existing["required_by"]["guideline_ids"] = list(
                    existing_guidelines.union(new_guidelines)
                )

                # Merge clause_nos
                existing_clauses = set(existing["required_by"].get("clause_nos", []))
                new_clauses = set(required_by.get("clause_nos", []))
                existing["required_by"]["clause_nos"] = list(
                    existing_clauses.union(new_clauses)
                )

                # Merge activity_ids
                existing_activities = set(
                    existing["required_by"].get("activity_ids", [])
                )
                new_activities = set(required_by.get("activity_ids", []))
                existing["required_by"]["activity_ids"] = list(
                    existing_activities.union(new_activities)
                )

                # Merge evidence items
                existing_evidence_list = existing["required_by"].get("evidence", [])
                if not isinstance(existing_evidence_list, list):
                    existing_evidence_list = []

                new_evidence_list = required_by.get("evidence", [])
                if not isinstance(new_evidence_list, list):
                    new_evidence_list = []

                # Create a set of existing evidence IDs for quick lookup
                existing_evidence_ids = set()
                for item in existing_evidence_list:
                    if isinstance(item, dict) and "evidence_id" in item:
                        existing_evidence_ids.add(item["evidence_id"])

                # Add new evidence items that don't exist already
                for new_item in new_evidence_list:
                    if isinstance(new_item, dict) and "evidence_id" in new_item:
                        if new_item["evidence_id"] not in existing_evidence_ids:
                            existing_evidence_list.append(new_item)
                            existing_evidence_ids.add(new_item["evidence_id"])

                existing["required_by"]["evidence"] = existing_evidence_list

        except Exception as e:
            current_app.logger.error(f"Error merging group {i}: {str(e)}")
            continue

    return list(merged_evidence.values())


def count_clauses_with_evidence(consolidated_evidence, all_clauses):
    """Count how many clauses have actual evidence."""
    clauses_with_evidence = set()

    for evidence_group in consolidated_evidence:
        clauses_with_evidence.update(evidence_group["required_by"]["clause_nos"])

    return len(clauses_with_evidence)


@audit_bp.route("/my_projects", methods=["GET"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def my_projects():
    """This route returns the list of project created by auditor"""
    add_to_breadcrumb(request.full_path, "My Project")
    if current_user.is_authenticated and current_user.auditor_profile_id:
        print(current_user.is_authenticated, current_user.auditor_profile_id)
        try:
            guideline_id = request.args.get("guideline_id")
            org_id = request.args.get("org_id")
            auditor_id = current_user.auditor_profile_id

            filters = {"auditing_firm": auditor_id}
            if guideline_id:
                filters["guidelines"] = guideline_id

            if org_id:
                filters["client"] = org_id

            projects = (
                Projects.query.filter_by(**filters)
                .options(
                    db.joinedload(Projects.documentation)
                )  #  load documentation relationship according to the projects
                .distinct(Projects.id)
                .order_by(Projects.id.desc())  # Show newest first
                .all()
            )
            print("projects", projects)
            print("I am hitting till here")
            for item in projects:
                print(item.project_guidelines)
            return render_template("my_project.html", my_projects=projects)

        except Exception as e:
            flash("Something Went Wrong", "warning")
            print(e)
            return redirect(request.referrer)
    else:
        flash("Please Login", "warning")
        return redirect(url_for("main.login"))


# project documentation section routes start from here
@audit_bp.route("/project_documentation/<int:project_id>", methods=["GET", "POST"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def project_documentation(project_id):
    """This route handles documentation for specific projects"""
    add_to_breadcrumb(request.full_path, "Project Documentation")

    if not current_user.is_authenticated or not current_user.auditor_profile_id:
        flash("Please Login", "warning")
        return redirect(url_for("main.login"))

    try:
        # Check if project exists and belongs to the current auditor
        project = Projects.query.filter_by(
            id=project_id, auditing_firm=current_user.auditor_profile_id
        ).first_or_404()

        if request.method == "POST":
            return handle_project_documentation_submission(project_id)

        # GET request - check if there's existing documentation for this project
        existing_doc = Documentation.query.filter_by(
            project_id=project_id, auditor_profile_id=current_user.auditor_profile_id
        ).first()

        # ========== FETCH DATA FOR EXECUTIVE SUMMARY ==========
        
        # 1. Get locations from the client's profile page
        locations = []
        if project.client_rel:
            # Fetch locations from the client's organization
            client_org = project.client_rel
            # Assuming there's a relationship or table for client locations
            # You may need to adjust this based on your actual data model
            if hasattr(client_org, 'addresses'):
                locations = client_org.addresses
            elif hasattr(client_org, 'locations'):
                locations = client_org.locations
        
        # 2. Get departments from the client's profile page
        departments = []
        if project.departments:
            departments = project.departments
        elif project.primary_department:
            # If only primary department exists, create a list with just that
            departments = [project.primary_department]
        
        # 3. Get all clause statistics for this project
        clause_statistics = get_project_clause_statistics(project_id)
        
        # 4. Get severity statistics
        severity_stats = get_project_severity_statistics(project_id)
        
        # 5. Get evidence statistics
        evidence_stats = get_project_evidence_statistics(project_id)
        
        # 6. Get audit organization name
        audit_org_name = None
        if current_user.auditor_profile_id:
            audit_org = AuditOrganization.query.get(current_user.auditor_profile_id)
            if audit_org:
                audit_org_name = audit_org.firm_name
        
        # 7. Handle multiple guidelines
        guidelines_list = []
        if project.guidelines_rel:
            # Single guideline case
            guideline = project.guidelines_rel
            if guideline.guideline_data:
                doc_details = guideline.guideline_data.get('DocumentDetails', {})
                guidelines_list.append({
                    'name': doc_details.get('DocumentName', 'Applicable Guidelines'),
                    'release_date': doc_details.get('IssuanceDate') or 'Not Specified'
                })
        elif project.project_guidelines:
            # Multiple guidelines case
            for pg in project.project_guidelines:
                if pg.guideline_data:
                    doc_details = pg.guideline_data.get('DocumentDetails', {})
                    guidelines_list.append({
                        'name': doc_details.get('DocumentName', 'Applicable Guidelines'),
                        'release_date': doc_details.get('IssuanceDate') or 'Not Specified'
                    })
        
        # For display, you might want to join multiple guidelines
        if guidelines_list:
            guideline_name = ", ".join([g['name'] for g in guidelines_list])
            # For release date, you might want to show the earliest or all
            guideline_release_date = ", ".join([g['release_date'] for g in guidelines_list if g['release_date'] != 'Not Specified'])
        else:
            guideline_name = "Applicable Guidelines"
            guideline_release_date = "Not Specified"
        # 8. Get assessment period
        assessment_start = project.assesment_start_date.strftime('%d %B %Y') if project.assesment_start_date else 'Not Started'
        assessment_end = project.assesment_end_date.strftime('%d %B %Y') if project.assesment_end_date else 'Present'
        
        # 9. Calculate all_clauses_completed status
        all_clauses_completed = check_all_clauses_completed(project_id)

        # ========== DEBUGGING: Print the structure of your data ==========
        print("=" * 50)
        print("DEBUG: clause_statistics structure:")
        print(f"Type: {type(clause_statistics)}")
        print(f"Keys: {clause_statistics.keys() if isinstance(clause_statistics, dict) else 'Not a dict'}")
        print(f"Full clause_statistics: {clause_statistics}")
        print("=" * 50)
        
        print("DEBUG: severity_stats structure:")
        print(f"Type: {type(severity_stats)}")
        print(f"Keys: {severity_stats.keys() if isinstance(severity_stats, dict) else 'Not a dict'}")
        print(f"Full severity_stats: {severity_stats}")
        print("=" * 50)
        
        print("DEBUG: evidence_stats structure:")
        print(f"Type: {type(evidence_stats)}")
        print(f"Keys: {evidence_stats.keys() if isinstance(evidence_stats, dict) else 'Not a dict'}")
        print(f"Full evidence_stats: {evidence_stats}")
        print("=" * 50)


        return render_template(
            "documentation.html", 
            documentation=existing_doc, 
            project=project,
            # Executive summary data
            locations=locations,
            departments=departments,
            clause_statistics=clause_statistics,
            severity_stats=severity_stats,
            evidence_stats=evidence_stats,
            audit_org_name=audit_org_name,
            client_name=project.client_rel.name if project.client_rel else 'Client',
            guideline_name=guideline_name or 'Applicable Guidelines',
            guideline_release_date=guideline_release_date or 'Not Specified',
            assessment_start=assessment_start,
            assessment_end=assessment_end,
            all_clauses_completed=all_clauses_completed,
            overall_project_severity=calculate_overall_severity(severity_stats),
            severity_color_class=get_severity_color_class(calculate_overall_severity(severity_stats))
        )

    except Exception as e:
        flash("Something Went Wrong", "warning")
        print(f"Error in project_documentation route: {str(e)}")
        import traceback

        traceback.print_exc()
        return redirect(request.referrer)

def check_all_clauses_completed(project_id):
    """Check if all applicable clauses are completed"""
    try:
        # Get all project clauses
        project_clauses = db.session.query(ProjectClause).join(
            ProjectGuideline, ProjectClause.project_guideline_id == ProjectGuideline.id
        ).filter(
            ProjectGuideline.project_id == project_id,
            ProjectClause.applicability == True
        ).all()
        
        for clause in project_clauses:
            if clause.assessment_status != "Completed":
                return False
        return True
    except Exception as e:
        print(f"Error checking clauses completed: {str(e)}")
        return False


def calculate_overall_severity(severity_stats):
    """Calculate overall project severity"""
    if severity_stats['counts']['Critical'] > 0:
        return 'Critical'
    elif severity_stats['counts']['Major'] > 0:
        return 'Major'
    elif severity_stats['counts']['Significant'] > 0:
        return 'Significant'
    elif severity_stats['counts']['Minor'] > 0:
        return 'Minor'
    else:
        return 'No findings noted'


def get_severity_color_class(severity):
    """Get color class for severity badge"""
    color_map = {
        'Critical': 'bg-red-600 text-white',
        'Major': 'bg-orange-500 text-white',
        'Significant': 'bg-yellow-500 text-gray-900',
        'Minor': 'bg-blue-400 text-white',
        'No findings noted': 'bg-green-500 text-white'
    }
    return color_map.get(severity, 'bg-gray-400 text-white')



def handle_project_documentation_submission(project_id):
    """Handle the documentation form submission for a specific project"""
    try:
        print(f"Starting documentation submission for project {project_id}...")

        # Check if documentation already exists for this project
        existing_doc = Documentation.query.filter_by(
            project_id=project_id, auditor_profile_id=current_user.auditor_profile_id
        ).first()

        if existing_doc:
            # Update existing documentation
            print("Updating existing documentation")
            return update_existing_documentation(existing_doc)
        else:
            # Create new documentation
            print("Creating new documentation")
            return create_new_project_documentation(project_id)

    except Exception as e:
        db.session.rollback()
        flash("Error saving documentation", "danger")
        print(f"Error handling documentation submission: {str(e)}")
        import traceback

        traceback.print_exc()
        return redirect(request.referrer)


def create_new_project_documentation(project_id):
    """Create new documentation record for a specific project"""
    try:
        print(f"Creating new documentation record for project {project_id}...")

        # Handle release_date - convert empty string to None
        release_date = request.form.get("release_date")
        if release_date == "":
            release_date = None

        # Get project details to pre-fill some fields
        project = Projects.query.get(project_id)

        # Generate a project-specific document ID
        document_id = f"DOC-{project_id}-{int(datetime.now().timestamp())}"

       # Get locations and departments from the project
        locations_data = []
        if project.client_rel:
            # Check if client has addresses/locations
            if hasattr(project.client_rel, 'addresses') and project.client_rel.addresses:
                for addr in project.client_rel.addresses:
                    # Build complete address string
                    address_parts = []
                    if hasattr(addr, 'address_line1') and addr.address_line1:
                        address_parts.append(addr.address_line1)
                    if hasattr(addr, 'address_line2') and addr.address_line2:
                        address_parts.append(addr.address_line2)
                    if hasattr(addr, 'city') and addr.city:
                        address_parts.append(addr.city)
                    if hasattr(addr, 'state') and addr.state:
                        address_parts.append(addr.state)
                    if hasattr(addr, 'country') and addr.country:
                        address_parts.append(addr.country)
                    if hasattr(addr, 'postal_code') and addr.postal_code:
                        address_parts.append(addr.postal_code)
                    
                    full_address = ", ".join(filter(None, address_parts))
                    
                    locations_data.append({
                        'city': addr.city if hasattr(addr, 'city') else '',
                        'country': addr.country if hasattr(addr, 'country') else '',
                        'address': full_address  # Now using full address instead of address_id
                    })
            elif hasattr(project.client_rel, 'locations') and project.client_rel.locations:
                # Alternative if using locations instead of addresses
                for loc in project.client_rel.locations:
                    locations_data.append({
                        'city': loc.city if hasattr(loc, 'city') else '',
                        'country': loc.country if hasattr(loc, 'country') else '',
                        'address': loc.full_address if hasattr(loc, 'full_address') else ''
                    })
        
        departments_data = []
        if project.departments:
            seen = set()
            for dept in project.departments:
                if dept.department_name not in seen:
                    seen.add(dept.department_name)
                    departments_data.append({
                        'name': dept.department_name
                    })
        elif project.primary_department:
            departments_data.append({
                'name': project.primary_department.department_name
            })

        documentation = Documentation(
            auditor_profile_id=current_user.auditor_profile_id,
            created_by=current_user.id,
            project_id=project_id,
            # Document Control - pre-fill with project info
            document_preparation=request.form.get(
                "document_preparation",
                f"Audit Documentation for {project.project_name}",
            ),
            document_title=request.form.get(
                "document_title", f"Audit Report - {project.project_name}"
            ),
            document_id=request.form.get("document_id", document_id),
            document_version=request.form.get("document_version", "v1.0"),
            prepared_by=request.form.get("prepared_by"),
            reviewed_by=request.form.get("reviewed_by"),
            approved_by=request.form.get("approved_by"),
            released_by=request.form.get("released_by"),
            release_date=release_date,
            # Rich Text Fields
            introduction=request.form.get("introduction"),
            engagement_scope=request.form.get("engagement_scope"),
            activities_timelines=request.form.get("activities_timelines"),
            methodology_criteria=request.form.get("methodology_criteria"),
            executive_summary=request.form.get("executive_summary"),
            locations_data=locations_data if locations_data else None,  # Save as None if empty
            departments_data=departments_data if departments_data else None,  # Save as None if empty
            executive_summary_narrative=request.form.get("executive_summary_narrative"),
        )

        db.session.add(documentation)
        db.session.flush()
        print(f"Documentation created with ID: {documentation.id}")

        # Save related records
        save_change_history(documentation.id)
        save_distribution_list(documentation.id)
        save_audit_team(documentation.id)
        save_tools_used(documentation.id)

        db.session.commit()
        print("Documentation committed to database successfully!")
        flash("Documentation saved successfully!", "success")
        return redirect(url_for("audit.my_projects"))

    except Exception as e:
        db.session.rollback()
        print(f"Error in create_new_project_documentation: {str(e)}")
        import traceback

        traceback.print_exc()
        flash(f"Error creating documentation: {str(e)}", "danger")
        return redirect(request.referrer)


def update_existing_documentation(doc):
    """Update existing documentation"""
    try:
        print(f"Updating existing documentation ID: {doc.id}")

        # Handle release_date - convert empty string to None
        release_date = request.form.get("release_date")
        if release_date == "":
            release_date = None
        
        # Get the project to refresh locations and departments
        project = Projects.query.get(doc.project_id)

        # Update locations data
        locations_data = []
        if project and project.client_rel:
            if hasattr(project.client_rel, 'addresses') and project.client_rel.addresses:
                for addr in project.client_rel.addresses:
                    # Build complete address string
                    address_parts = []
                    if hasattr(addr, 'address_line1') and addr.address_line1:
                        address_parts.append(addr.address_line1)
                    if hasattr(addr, 'address_line2') and addr.address_line2:
                        address_parts.append(addr.address_line2)
                    if hasattr(addr, 'city') and addr.city:
                        address_parts.append(addr.city)
                    if hasattr(addr, 'state') and addr.state:
                        address_parts.append(addr.state)
                    if hasattr(addr, 'country') and addr.country:
                        address_parts.append(addr.country)
                    if hasattr(addr, 'postal_code') and addr.postal_code:
                        address_parts.append(addr.postal_code)
                    
                    full_address = ", ".join(filter(None, address_parts))
                    
                    locations_data.append({
                        'city': addr.city if hasattr(addr, 'city') else '',
                        'country': addr.country if hasattr(addr, 'country') else '',
                        'address': full_address
                    })
            elif hasattr(project.client_rel, 'locations') and project.client_rel.locations:
                for loc in project.client_rel.locations:
                    locations_data.append({
                        'city': loc.city if hasattr(loc, 'city') else '',
                        'country': loc.country if hasattr(loc, 'country') else '',
                        'address': loc.full_address if hasattr(loc, 'full_address') else ''
                    })

        # Update departments data
        departments_data = []
        if project:
            if project.departments:
                seen = set()
                for dept in project.departments:
                    if dept.department_name not in seen:
                        seen.add(dept.department_name)
                        departments_data.append({
                            'name': dept.department_name
                        })
            elif project.primary_department:
                departments_data.append({
                    'name': project.primary_department.department_name
                })
    

        # Update main documentation fields
        doc.document_preparation = request.form.get("document_preparation")
        doc.document_title = request.form.get("document_title")
        doc.document_version = request.form.get("document_version")
        doc.prepared_by = request.form.get("prepared_by")
        doc.reviewed_by = request.form.get("reviewed_by")
        doc.approved_by = request.form.get("approved_by")
        doc.released_by = request.form.get("released_by")
        doc.release_date = release_date
        doc.introduction = request.form.get("introduction")
        doc.engagement_scope = request.form.get("engagement_scope")
        doc.activities_timelines = request.form.get("activities_timelines")
        doc.methodology_criteria = request.form.get("methodology_criteria")
        doc.executive_summary = request.form.get("executive_summary")
        
        # Update locations and departments data
        doc.locations_data = locations_data if locations_data else None
        doc.departments_data = departments_data if departments_data else None
        
        doc.updated_at = func.current_timestamp()

        # Delete existing related records
        DocumentChangeHistory.query.filter_by(documentation_id=doc.id).delete()
        DocumentDistribution.query.filter_by(documentation_id=doc.id).delete()
        AuditTeam.query.filter_by(documentation_id=doc.id).delete()
        AuditTools.query.filter_by(documentation_id=doc.id).delete()

        # Save new related records
        save_change_history(doc.id)
        save_distribution_list(doc.id)
        save_audit_team(doc.id)
        save_tools_used(doc.id)

        db.session.commit()
        print("Documentation updated successfully!")
        flash("Documentation updated successfully!", "success")

        # Redirect back to project documentation page
        return redirect(url_for("audit.my_projects"))

    except Exception as e:
        db.session.rollback()
        print(f"Error in update_existing_documentation: {str(e)}")
        import traceback

        traceback.print_exc()
        flash(f"Error updating documentation: {str(e)}", "danger")
        return redirect(url_for("audit.my_projects"))


# documenation section start from here


def save_change_history(doc_id):
    """Save document change history"""
    try:
        versions = request.form.getlist("change_version[]")
        dates = request.form.getlist("change_date[]")
        remarks = request.form.getlist("change_remarks[]")

        print(f"Saving {len(versions)} change history entries")

        for i, (version, date, remark) in enumerate(zip(versions, dates, remarks)):
            if version and date:  # Only save if required fields are present
                change_history = DocumentChangeHistory(
                    documentation_id=doc_id,
                    version=version,
                    change_date=date,
                    remarks=remark,
                )
                db.session.add(change_history)
                print(f"Added change history {i+1}: {version}")
    except Exception as e:
        print(f"Error saving change history: {str(e)}")
        raise


def save_distribution_list(doc_id):
    """Save document distribution list"""
    try:
        names = request.form.getlist("dist_name[]")
        organizations = request.form.getlist("dist_org[]")
        designations = request.form.getlist("dist_designation[]")
        emails = request.form.getlist("dist_email[]")

        print(f"Saving {len(names)} distribution entries")

        for i, (name, org, designation, email) in enumerate(
            zip(names, organizations, designations, emails)
        ):
            if name:  # Only save if name is present
                distribution = DocumentDistribution(
                    documentation_id=doc_id,
                    name=name,
                    organization=org,
                    designation=designation,
                    email=email,
                )
                db.session.add(distribution)
                print(f"Added distribution {i+1}: {name}")
    except Exception as e:
        print(f"Error saving distribution list: {str(e)}")
        raise


def save_audit_team(doc_id):
    """Save audit team members"""
    try:
        names = request.form.getlist("team_name[]")
        designations = request.form.getlist("team_designation[]")
        emails = request.form.getlist("team_email[]")
        qualifications = request.form.getlist("team_qualification[]")
        listed_statuses = request.form.getlist("team_listed[]")

        print(f"Saving {len(names)} audit team members")

        for i, (name, designation, email, qualification, listed) in enumerate(
            zip(names, designations, emails, qualifications, listed_statuses)
        ):
            if name:  # Only save if name is present
                team_member = AuditTeam(
                    documentation_id=doc_id,
                    name=name,
                    designation=designation,
                    email=email,
                    professional_qualifications=qualification,
                    listed_in_snapshot=listed,
                )
                db.session.add(team_member)
                print(f"Added team member {i+1}: {name}")
    except Exception as e:
        print(f"Error saving audit team: {str(e)}")
        raise


def save_tools_used(doc_id):
    """Save tools/software used"""
    try:
        tool_names = request.form.getlist("tool_name[]")
        versions = request.form.getlist("tool_version[]")
        licenses = request.form.getlist("tool_license[]")

        print(f"Saving {len(tool_names)} tools")

        for i, (tool_name, version, license_type) in enumerate(
            zip(tool_names, versions, licenses)
        ):
            if tool_name:  # Only save if tool name is present
                tool = AuditTools(
                    documentation_id=doc_id,
                    tool_name=tool_name,
                    version_control=version,
                    license_type=license_type,
                )
                db.session.add(tool)
                print(f"Added tool {i+1}: {tool_name}")
    except Exception as e:
        print(f"Error saving tools: {str(e)}")
        raise


UPLOAD_FOLDER = "evidences"
UPLOAD_FOLDER_1 = "uploads/evidences"
ALLOWED_EXTENSIONS = {
    "pdf",
    "png",
    "jpg",
    "jpeg",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "csv",
    "txt",
}

os.makedirs(UPLOAD_FOLDER_1, exist_ok=True)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@audit_bp.route("/upload_to_multiple_evidences", methods=["POST"])
def upload_to_multiple_evidences():
    """
    Uploads multiple files to provide evidence for multiple project-specific
    evidence artifacts simultaneously, using an AI service to generate
    context-aware answers for each.
    """

    saved_files = []
    processed_artifacts = {}
    try:
        evidence_ids = request.form.get("evidence_ids")
        input_files = request.files.getlist("evidence_files")

        if not evidence_ids or not evidence_ids.strip():
            flash("No evidence IDs provided", "danger")
            return redirect(request.referrer)

        if not input_files or all(not file.filename for file in input_files):
            flash("No files selected for upload", "warning")
            return redirect(request.referrer)

        evidence_list = [
            int(id.strip()) for id in evidence_ids.split(",") if id.strip().isdigit()
        ]
        if not evidence_list:
            flash("No valid evidence IDs found", "danger")
            return redirect(request.referrer)

        filter_evidence = (
            ProjectEvidenceArtifact.query.options(
                joinedload(ProjectEvidenceArtifact.project_control_activity)
            )
            .filter(ProjectEvidenceArtifact.id.in_(evidence_list))
            .all()
        )

        if not filter_evidence:
            flash("No matching project evidence artifacts found", "warning")
            return redirect(request.referrer)

        success_count = 0
        error_count = 0

        # process files
        for input_file in input_files:
            if not input_file or not input_file.filename:
                continue

            if not allowed_file(input_file.filename):
                flash(f"Invalid file type for {input_file.filename}.", "warning")
                continue

            timestamped = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
            stored_filename = secure_filename(f"{timestamped}_{input_file.filename}")
            full_physical_file_path = os.path.join(UPLOAD_FOLDER_1, stored_filename)
            db_file_path = os.path.join(UPLOAD_FOLDER, stored_filename)

            try:
                os.makedirs(os.path.dirname(full_physical_file_path), exist_ok=True)
                input_file.save(full_physical_file_path)
            except Exception as e:
                flash(f"Error saving file {input_file.filename}: {e}", "danger")
                continue

            saved_files.append(
                {
                    "original_name": input_file.filename,
                    "stored_filename": stored_filename,
                    "path": full_physical_file_path,
                    "db_path": db_file_path,
                    "content_type": input_file.mimetype,
                    "size": os.path.getsize(full_physical_file_path),
                }
            )

            # Try extract content (for AI)
            try:
                content = extract_content(full_physical_file_path)
                if not content or not content.strip():
                    flash(
                        f"Could not extract content from {input_file.filename}.",
                        "warning",
                    )
                    # continue but keep the file saved for user to download / view
                    content = ""
            except Exception as e:
                flash(
                    f"Error extracting content from {input_file.filename}: {e}",
                    "warning",
                )
                content = ""

            # For each artifact, create EvidenceFile row and run AI processing.
            for artifact in filter_evidence:
                try:
                    # create EvidenceFile row
                    ef = EvidenceFile(
                        project_evidence_artifact_id=artifact.id,
                        file_name=input_file.filename,
                        stored_filename=stored_filename,
                        file_path=db_file_path,
                        content_type=input_file.mimetype,
                        file_size=os.path.getsize(full_physical_file_path),
                    )
                    db.session.add(ef)

                    # AI processing (existing logic)
                    if (
                        not artifact.project_control_activity
                        or not artifact.project_control_activity.activity_description
                    ):
                        processed_artifacts[f"{artifact.id}_{stored_filename}"] = {
                            "status": "error",
                            "message": "Missing control info",
                        }
                        error_count += 1
                        continue

                    activity_desc = (
                        artifact.project_control_activity.activity_description
                    )
                    prompt = prompt_get_evidence_answer_activity(
                        artifact.id, artifact.item, activity_desc, content
                    )
                    res = generate_chat_output(prompt)
                    if not res:
                        processed_artifacts[f"{artifact.id}_{stored_filename}"] = {
                            "status": "error",
                            "message": "Empty AI response",
                        }
                        error_count += 1
                        continue

                    # attempt parse
                    try:
                        if res.strip().startswith("{"):
                            ai_answer = json.loads(res).get("answer")
                        else:
                            ai_answer = res
                    except Exception:
                        ai_answer = res

                    if ai_answer and ai_answer.strip():
                        artifact.evidence_text = ai_answer.strip()
                        # Optionally keep last file path in artifact.evidence_file_path for legacy
                        artifact.evidence_file_path = db_file_path
                        processed_artifacts[f"{artifact.id}_{stored_filename}"] = {
                            "status": "success",
                            "artifact": artifact.item,
                            "file": input_file.filename,
                        }
                        success_count += 1
                    else:
                        processed_artifacts[f"{artifact.id}_{stored_filename}"] = {
                            "status": "error",
                            "message": "AI empty",
                        }
                        error_count += 1

                except Exception as ex:
                    processed_artifacts[f"{artifact.id}_{stored_filename}"] = {
                        "status": "error",
                        "message": str(ex),
                    }
                    error_count += 1

        # commit all changes (EvidenceFile rows + artifact updates)
        try:
            db.session.commit()
        except Exception as db_err:
            db.session.rollback()
            # remove saved files if commit fails
            for f in saved_files:
                try:
                    if os.path.exists(f["path"]):
                        os.remove(f["path"])
                except Exception:
                    pass
            flash(f"Database error: {db_err}", "danger")
            return redirect(request.referrer)

        # user-facing messages
        if success_count:
            flash(
                f"Successfully processed {success_count} evidence artifact(s).",
                "success",
            )
        if error_count:
            flash(f"Processing had {error_count} errors; files were saved.", "warning")

        return redirect(request.referrer)

    except Exception as e:
        db.session.rollback()
        # cleanup saved files
        for f in saved_files:
            try:
                if os.path.exists(f["path"]):
                    os.remove(f["path"])
            except Exception:
                pass
        flash(f"Unexpected error: {e}", "danger")
        return redirect(request.referrer)


@audit_bp.route("/get_uploaded_files")
def get_uploaded_files():
    """Get list of uploaded files for evidence items"""
    evidence_ids = request.args.get("evidence_ids", "").split(",")

    try:
        evidence_list = [int(id.strip()) for id in evidence_ids if id.strip().isdigit()]

        # Query for files associated with these evidence items
        evidence_files = ProjectEvidenceArtifact.query.filter(
            ProjectEvidenceArtifact.id.in_(evidence_list),
            ProjectEvidenceArtifact.evidence_file_path.isnot(None),
        ).all()

        files = []
        for evidence in evidence_files:
            if evidence.evidence_file_path:
                filename = os.path.basename(evidence.evidence_file_path)
                files.append(
                    {
                        "id": evidence.id,
                        "filename": filename,
                        "download_url": url_for(
                            "audit.download_evidence_file", filename=filename
                        ),
                        "upload_date": (
                            evidence.updated_at.isoformat()
                            if evidence.updated_at
                            else None
                        ),
                    }
                )

        return jsonify({"status": "success", "files": files})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@audit_bp.route("/delete_uploaded_evidence/<int:file_id>", methods=["POST"])
def delete_uploaded_evidence(file_id):
    file_row = EvidenceFile.query.get_or_404(file_id)
    # authorization checks: ensure current_user can delete this artifact's files
    # if not current_user_can_edit(file_row.artifact): abort(403)

    file_path = os.path.join(
        UPLOAD_FOLDER_1, file_row.stored_filename
    )  # or use file_row.file_path
    try:
        # delete file on disk if exists
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        # log but continue to remove DB record
        current_app.logger.exception(f"Error removing file {file_path}: {e}")

    try:
        db.session.delete(file_row)
        db.session.commit()
        flash("Uploaded file removed.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error removing file record: {e}", "danger")

    return redirect(request.referrer)


@audit_bp.route("/evidence_file/<int:file_id>/download")
def download_evidence_file(file_id):
    file_row = EvidenceFile.query.get_or_404(file_id)
    # check permission:
    # if not current_user_can_view(file_row.artifact): abort(403)

    stored_filename = file_row.stored_filename
    full_dir = os.path.abspath(UPLOAD_FOLDER_1)
    return send_from_directory(
        full_dir, stored_filename, as_attachment=True, download_name=file_row.file_name
    )


@audit_bp.route("/evaluate_all_project", methods=["POST"])
def evaluate_all_projects():
    """
    Initiates a full AI-driven evaluation of all control activities for a given project,
    updating each project-specific record with observations, findings, and a compliance status.
    Only evaluates activities from clauses marked as applicable.
    """
    try:
        project_name = request.form.get("project_name")
        if not project_name:
            flash("Project name is required.", "danger")
            return redirect(request.referrer)

        auditing_firm_id = current_user.auditor_profile_id

        # This helper function must be the corrected version that works with project instances
        result = generate_all_project_prompts(
            project_name=project_name,
            auditing_firm_id=auditing_firm_id,
            db_session=db.session,
        )

        control_prompts = result.get("control_activity_prompts", [])
        applicable_clauses_count = result.get("applicable_clauses_count", 0)
        non_applicable_clauses_count = result.get("non_applicable_clauses_count", 0)

        if not control_prompts:
            flash(
                f"No applicable control activities found for this project. "
                f"Applicable clauses: {applicable_clauses_count}, "
                f"Non-applicable clauses: {non_applicable_clauses_count}",
                "warning",
            )
            return redirect(request.referrer)

        for i, prompt in enumerate(control_prompts, start=1):
            try:
                res = generate_chat_output(prompt)
                output = json.loads(res) if isinstance(res, str) else res
            except Exception as e:
                flash(f"Error generating output for an activity: {str(e)}", "danger")
                continue

            if not isinstance(output, dict) or "control_id" not in output:
                flash(
                    f"Missing or invalid 'control_id' in AI response for an activity.",
                    "warning",
                )
                continue

            try:
                # --- CORE CHANGE: Query the project-specific table ---
                project_activity = ProjectControlActivity.query.get(
                    output["control_id"]
                )

                if not project_activity:
                    flash(
                        f"Project control activity with ID {output['control_id']} not found.",
                        "danger",
                    )
                    continue

                # Update the project-specific record with the AI's evaluation
                project_activity.auditor_observation = output.get("observations")
                project_activity.recommendations = output.get("recommendations")
                project_activity.findings = output.get("findings")
                project_activity.compliant_status = output.get(
                    "overall_compliance_status"
                )

                db.session.commit()
                flash(
                    f"Evaluated activity: {project_activity.activity_name}", "success"
                )

            except Exception as e:
                db.session.rollback()
                flash(
                    f"Database error while updating activity {output['control_id']}: {str(e)}",
                    "danger",
                )
                continue

        return redirect(request.referrer)

    except Exception as e:
        flash(f"An unexpected error occurred during evaluation: {str(e)}", "danger")
        return redirect(request.referrer)


@audit_bp.route("/reevaluate_activity", methods=["POST"])
def reevaluate_activity():
    """
    EVE v3 Pipeline — Evaluate a single project control activity.
    Triggers Steps 5 → 6 → 7 for the activity.
    """
    try:
        project_control_activity_id = request.form.get("activity_code")
        user_prompt = request.form.get("user_input", "")

        if not project_control_activity_id:
            flash("Activity ID is required for evaluation.", "error")
            return redirect(request.referrer)

        project_control_activity = ProjectControlActivity.query.get(
            int(project_control_activity_id)
        )
        if not project_control_activity:
            flash(f"No activity found with ID: {project_control_activity_id}", "error")
            return redirect(request.referrer)

        # Get upload base path
        upload_base_path = current_app.config.get(
            "UPLOAD_FOLDER",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../uploads")
        )

        # Get project checklist for this control activity
        from app.models.eve_models import ProjectChecklist
        checklist = ProjectChecklist.query.filter_by(
            project_control_activity_id=project_control_activity.id
        ).first()

        if not checklist:
            flash(
                "No EVE checklist found for this activity. "
                "Please ensure checklist generation is complete.",
                "error"
            )
            return redirect(request.referrer)

        # Get evidence artifacts
        evidence_artifacts = project_control_activity.submitted_evidences or []

        # Trigger EVE Step 5 for each evidence
        from app.services.eve_step5 import run_eve_step5_for_all_evidence
        from app.services.eve_step678 import run_eve_step6_and_7

        step5_tasks = 0
        if evidence_artifacts:
            for evidence in evidence_artifacts:
                run_eve_step5_for_all_evidence.apply_async(
                    args=[checklist.id, upload_base_path],
                    queue='eve_evaluate'
                )
                step5_tasks += 1

        # Trigger Step 6 + 7 with delay to allow Step 5 to complete
        countdown = max(30, step5_tasks * 10)
        run_eve_step6_and_7.apply_async(
            args=[project_control_activity.id, current_user.id],
            queue='eve_evaluate',
            countdown=countdown
        )

        current_app.logger.info(
            f"[EVE v3] Triggered evaluation for activity_id={project_control_activity_id}, "
            f"evidence={step5_tasks}, countdown={countdown}s"
        )

        flash(
            f"EVE v3 evaluation started! "
            f"{step5_tasks} evidence file(s) being processed. "
            f"Results will appear in ~{countdown} seconds.",
            "success"
        )
        return redirect(request.referrer)

    except Exception as e:
        current_app.logger.exception(f"Error in EVE v3 reevaluate_activity: {str(e)}")
        flash(f"Error starting evaluation: {str(e)}", "error")
        return redirect(request.referrer)


@audit_bp.route("/delete-evidence", methods=["POST"])
def delete_evidence():
    """
    Deletes a project-specific evidence artifact and provides user feedback.
    """
    evidence_id_str = request.form.get("evidence_id")

    if not evidence_id_str:
        flash("Error: No evidence ID provided.", "error")
        return redirect(request.referrer)

    try:
        evidence_id = int(evidence_id_str)
        # --- CORE CHANGE: Query the project-specific table ---
        artifact = ProjectEvidenceArtifact.query.get(evidence_id)

        if artifact:
            db.session.delete(artifact)
            db.session.commit()
            flash("Project evidence artifact deleted successfully!", "success")
        else:
            flash(
                f"Error: Project evidence artifact with ID {evidence_id} not found.",
                "error",
            )

    except ValueError:
        flash("Error: Invalid evidence ID format.", "error")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting evidence: {str(e)}")
        flash(f"An unexpected error occurred: {e}", "error")

    return redirect(request.referrer)


@audit_bp.route("/delete-question", methods=["POST"])
def delete_question():
    """
    Deletes a project-specific interview question and provides user feedback.
    """
    question_id_str = request.form.get("question_id")
    if not question_id_str:
        flash("Error: No question ID provided.", "error")
        return redirect(request.referrer)

    try:
        question_id = int(question_id_str)
        # --- CORE CHANGE: Query the project-specific table ---
        question = ProjectInterviewQuestion.query.get(question_id)

        if question:
            db.session.delete(question)
            db.session.commit()
            flash("Question deleted successfully!", "success")
        else:
            flash(f"Error: Question with ID {question_id} not found.", "error")

    except ValueError:
        flash("Error: Invalid question ID format.", "error")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting question: {str(e)}")
        flash(f"An unexpected error occurred: {e}", "error")

    return redirect(request.referrer)


# @audit_bp.route('/project_activities', methods=['GET'])
# def get_project_activities():
#     return render_template('project_details.html')

# @audit_bp.route('/project_details', methods=['GET'])
# def get_project_details():
#     project_id = request.args.get("project_id")
#     project = Projects.query.get(project_id)

#     return render_template('my_projects_new.html')


@audit_bp.route("/project_clause/<int:clause_id>/activities", methods=["GET"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def get_clause_activities(clause_id):
    """
    Fetches all control activities for a given clause, preparing the data
    needed for the detailed view, including the refetch functionality.
    """
    add_to_breadcrumb(request.full_path, "Project Details")

    # Eagerly load the entire hierarchy from clause down to control activities
    clause = (
        db.session.query(ProjectClause)
        .options(
            joinedload(ProjectClause.project_guideline),
            joinedload(ProjectClause.project_compliance_activities).joinedload(
                ProjectComplianceActivity.project_control_activities
            ),
        )
        .filter_by(id=clause_id)
        .first_or_404()
    )

    project = Projects.query.get(clause.project_guideline.project_id)

    # Flatten the list of control activities
    control_activities = []
    for compliance_activity in clause.project_compliance_activities:
        for control in compliance_activity.project_control_activities:
            control_activities.append(
                {
                    "id": control.id,
                    "original_control_id": control.original_control_id,
                    "activity_code": control.activity_code,
                    "activity_name": control.activity_name,
                    "parent_activity_id": compliance_activity.id,
                    "parent_activity_description": compliance_activity.activity_description,
                    "parent_applicability": compliance_activity.applicability,
                }
            )

    # ✅ Order by control activity id
    control_activities.sort(key=lambda x: x["id"])

    return render_template(
        "project_details.html",
        project=project,
        clause=clause,
        control_activities=control_activities,
    )


@audit_bp.route("/bulk_update_applicability", methods=["POST"])
@login_required
def bulk_update_applicability():
    try:
        data = request.get_json()
        clause_ids = data.get("clause_ids", [])
        applicability = data.get("applicability", True)

        if not clause_ids:
            return jsonify({"status": "error", "message": "No clauses selected"}), 400

        # Check if user has free report used
        if current_user.free_report_used:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Editing disabled - Free report already used",
                    }
                ),
                403,
            )

        # Update each clause
        updated_count = 0
        for clause_id in clause_ids:
            # Find the clause
            clause = ProjectClause.query.get(clause_id)
            if clause:
                clause.applicability = applicability
                updated_count += 1

        # Commit changes
        db.session.commit()

        return jsonify(
            {
                "status": "success",
                "message": f"Updated {updated_count} clause(s)",
                "updated_count": updated_count,
            }
        )

    except Exception as e:
        db.session.rollback()
        return (
            jsonify(
                {"status": "error", "message": f"Error updating clauses: {str(e)}"}
            ),
            500,
        )


@audit_bp.route("/clause/<int:clause_id>/test-steps", methods=["GET"])
@login_required
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def clause_test_steps(clause_id):
    """
    Fetches all control activities for a given clause, preparing the data
    needed for the detailed view, including all evidences from all APPLICABLE activities
    and compliance status.
    """
    add_to_breadcrumb(request.full_path, "Clause Details")

    # Get the clause
    clause = (
        db.session.query(ProjectClause)
        .options(joinedload(ProjectClause.project_guideline))
        .filter_by(id=clause_id)
        .first_or_404()
    )

    project = Projects.query.get(clause.project_guideline.project_id)

    # Get only APPLICABLE project compliance activities for this clause
    project_compliance_activities = (
        db.session.query(ProjectComplianceActivity)
        .filter_by(project_clause_id=clause_id)
        .all()
    )

    # Collect all evidences and control activities from only APPLICABLE activities in this clause
    all_evidences = []
    all_control_activities = []
    applicable_control_activities = []
    total_evidence_count = 0

    for pca in project_compliance_activities:
        # Get all control activities for this compliance activity
        control_activities = (
            db.session.query(ProjectControlActivity)
            .filter_by(project_compliance_activity_id=pca.id)
            .options(
                joinedload(ProjectControlActivity.submitted_evidences),
                joinedload(ProjectControlActivity.project_test_procedure),
                joinedload(ProjectControlActivity.project_compliance_activity),
            )
            .all()
        )

        for control_activity in control_activities:
            # Get the parent compliance activity to check applicability
            parent_compliance_activity = control_activity.project_compliance_activity
            parent_applicability = parent_compliance_activity.applicability

            # Count evidences for this activity
            evidence_count = (
                len(control_activity.submitted_evidences)
                if control_activity.submitted_evidences
                else 0
            )
            total_evidence_count += evidence_count  # Add to total

            display_activity_name = (
                control_activity.project_compliance_activity.activity_description
            )
            activity_data = {
                "id": control_activity.id,
                "activity_name": display_activity_name,
                "activity_code": control_activity.activity_code,
                "activity_description": control_activity.activity_description,
                "compliant_status": control_activity.compliant_status
                or "To be Assessed",
                "auditor_observation": control_activity.auditor_observation,
                "findings": control_activity.findings,
                "recommendations": control_activity.recommendations,
                "owner": control_activity.owner,
                "control_type": control_activity.control_type,
                "is_applicable": parent_applicability,
                "compliance_activity_id": parent_compliance_activity.id,
                "project_test_procedure": control_activity.project_test_procedure,
                "overall_severity_classification": control_activity.overall_severity_classification,
                 # Add these fields for evidence admissibility
                "evidence_admissibility_decision": control_activity.evidence_admissibility_decision,
                "evidence_quality_rating": control_activity.evidence_quality_rating,
                # Add a calculated field for easy use in template
                "evidence_received": (
                    control_activity.evidence_admissibility_decision == "Yes" and 
                    control_activity.evidence_quality_rating == "STRONG"
                )
            }
            all_control_activities.append(activity_data)

            # Add to applicable-only list if applicable
            if parent_applicability:
                applicable_control_activities.append(activity_data)

            # Add activity information with evidences
            if parent_applicability:
                for evidence in control_activity.submitted_evidences:
                    all_evidences.append(
                        {
                            "activity_name": display_activity_name,
                            "activity_code": control_activity.activity_code,
                            "category": evidence.category,
                            "item": evidence.item,
                            "evidence_text": evidence.evidence_text,
                            "evidence_file_path": evidence.evidence_file_path,
                            "id": evidence.id,
                            "is_applicable": True,
                        }
                    )

    # Define natural sorting function for activity_code
    def natural_sort_key(activity):
        text = (
            activity.get("activity_code", "")
            if isinstance(activity, dict)
            else activity.activity_code
        )
        if not text:
            return [float("inf")]
        return [
            int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", str(text))
        ]

    # Sort all control activities using natural sorting
    sorted_all_control_activities = sorted(all_control_activities, key=natural_sort_key)
    sorted_applicable_control_activities = sorted(
        applicable_control_activities, key=natural_sort_key
    )

    # ============== CALCULATE ACTUAL EVIDENCE FILES COUNT ==============
    actual_evidence_files_count = 0
    evidence_files_details = []
    
    for evidence in all_evidences:
        # Check if evidence has actual file attachments
        if evidence.get('evidence_file_path'):
            actual_evidence_files_count += 1
            evidence_files_details.append({
                'activity_code': evidence.get('activity_code'),
                'activity_name': evidence.get('activity_name'),
                'file_path': evidence.get('evidence_file_path'),
                'category': evidence.get('category')
            })
    
    logger.info(f"📁 Actual evidence files received: {actual_evidence_files_count} out of {len(all_evidences)} total evidence entries")
    # ================================================================
   # ============== CALCULATE ACTIVITIES WITH EVIDENCE RECEIVED ==============
    # Count activities that have evidence_received = True (admissible and strong)
    activities_with_evidence = sum(1 for activity in applicable_control_activities if activity.get("evidence_received", False))
    total_applicable_activities_count = len(applicable_control_activities)
    
    # Calculate percentage of activities with evidence
    activities_evidence_percentage = 0
    if total_applicable_activities_count > 0:
        activities_evidence_percentage = round((activities_with_evidence / total_applicable_activities_count) * 100)
    
    # Determine color class based on percentage for visual feedback
    if activities_evidence_percentage >= 75:
        activities_evidence_color_class = "text-green-600"
        activities_evidence_bg_class = "bg-green-100"
        activities_evidence_border_class = "border-green-200"
        activities_evidence_progress_class = "bg-green-500"
    elif activities_evidence_percentage >= 50:
        activities_evidence_color_class = "text-yellow-600"
        activities_evidence_bg_class = "bg-yellow-100"
        activities_evidence_border_class = "border-yellow-200"
        activities_evidence_progress_class = "bg-yellow-500"
    elif activities_evidence_percentage >= 25:
        activities_evidence_color_class = "text-orange-600"
        activities_evidence_bg_class = "bg-orange-100"
        activities_evidence_border_class = "border-orange-200"
        activities_evidence_progress_class = "bg-orange-500"
    else:
        activities_evidence_color_class = "text-red-600"
        activities_evidence_bg_class = "bg-red-100"
        activities_evidence_border_class = "border-red-200"
        activities_evidence_progress_class = "bg-red-500"
    
    logger.info(f"📊 Activities with evidence: {activities_with_evidence} out of {total_applicable_activities_count} ({activities_evidence_percentage}%)")
    # ================================================================


    # ============== CRITICAL FIX: Calculate statistics directly from applicable_control_activities ==============
    # Initialize statistics
    statistics = {
        "total": len(applicable_control_activities),
        "Compliant": 0,
        "Partially Compliant": 0,
        "Non-Compliant": 0,
        "Not Assessed": 0,
    }

    # Count statuses from applicable activities
    for activity in applicable_control_activities:
        status = activity.get("compliant_status")

        if status == "Compliant":
            statistics["Compliant"] += 1
        elif status == "Partially Compliant":
            statistics["Partially Compliant"] += 1
        elif status == "Non-Compliant":
            statistics["Non-Compliant"] += 1
        else:
            statistics["Not Assessed"] += 1

    logger.info(f"📊 Statistics calculated from applicable activities: {statistics}")
    # ===========================================================================================================

    # Calculate overall clause compliance status
    clause_status_info = calculate_clause_compliance_status(clause_id)

    # ⭐ IMPORTANT: Ensure statistics are included in clause_status_info
    clause_status_info["statistics"] = statistics

    # Check if there's a manually set status in the database
    current_overall_status = clause.overall_compliance_status or "To be Assessed"

    if current_overall_status != "To be Assessed":
        # Override the calculated status with the manually set one
        clause_status_info["text"] = current_overall_status
        clause_status_info["css_class"] = get_status_css_class(current_overall_status)
        clause_status_info["is_manual"] = True
        clause_status_info["details"] = "Manually set compliance status"
        # Keep the statistics even when manually set
        clause_status_info["statistics"] = statistics
    else:
        clause_status_info["is_manual"] = False
        # If no manual status is set and the calculated status is different, update it
        if clause_status_info["text"] != current_overall_status:
            clause.overall_compliance_status = clause_status_info["text"]
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error updating clause status: {str(e)}")


     
    # ============== CALCULATE OVERALL SEVERITY LEVEL ==============
    # Define severity hierarchy (highest to lowest)
    severity_hierarchy = {
        'Critical': 5,
        'Major': 4,
        'Significant': 3,
        'Minor': 2,
        'No findings noted': 1,
        None: 0,
        '': 0,
        'Not Classified': 0
    }
    
    overall_severity_level = 'No findings noted'
    highest_severity_score = 0
    severity_details = []
    
    # Initialize severity counts
    severity_counts = {
        'Critical': 0,
        'Major': 0,
        'Significant': 0,
        'Minor': 0,
        'No findings noted': 0
    }
    
    # IMPORTANT: Loop through applicable_control_activities, not all_control_activities
    for activity in applicable_control_activities:
        # Get the overall_severity_classification from the activity
        # Check multiple possible field names
        activity_severity = activity.get('overall_severity_classification')
        
        # If not found, try alternative field names
        if not activity_severity or activity_severity == 'Not Classified':
            activity_severity = activity.get('overall_severity')
        
        # If still not found, try to get from the original object if it exists
        if not activity_severity or activity_severity == 'Not Classified':
            # Try to get the actual database object
            
            control_activity = ProjectControlActivity.query.get(activity.get('id'))
            if control_activity:
                activity_severity = control_activity.overall_severity_classification
        
        # Default to 'No findings noted' if nothing found and activity is compliant
        if not activity_severity or activity_severity == 'Not Classified':
            if activity.get('compliant_status') == 'Compliant':
                activity_severity = 'No findings noted'
            else:
                activity_severity = 'Not Classified'
        
        # Only count activities that have a severity classification
        if activity_severity and activity_severity != 'Not Classified':
            severity_score = severity_hierarchy.get(activity_severity, 0)
            
            # Add to severity details
            severity_details.append({
                'activity_code': activity.get('activity_code'),
                'activity_name': activity.get('activity_name'),
                'severity': activity_severity,
                'score': severity_score,
                'compliant_status': activity.get('compliant_status')
            })
            
            # Update counts
            if activity_severity in severity_counts:
                severity_counts[activity_severity] = severity_counts.get(activity_severity, 0) + 1
            
            # Track highest severity
            if severity_score > highest_severity_score:
                highest_severity_score = severity_score
                overall_severity_level = activity_severity
    
    # If no activities have findings, set to 'No findings noted'
    if not severity_details:
        overall_severity_level = 'No findings noted'
    
    logger.info(f"📊 Overall Severity Level: {overall_severity_level} (score: {highest_severity_score})")
    logger.info(f"📊 Severity Distribution: {severity_counts}")
    logger.info(f"📊 Severity Details: {severity_details}")
    # ================================================================

    # Get consolidated summary from database
    consolidated_summary_record = ClauseConsolidatedSummary.query.filter_by(
        clause_id=clause_id
    ).first()

    consolidated_summary = None
    if consolidated_summary_record:
        consolidated_summary = consolidated_summary_record.consolidated_data

        # Filter consolidated summary to only include applicable activities
        if consolidated_summary:
            applicable_activity_codes = [
                activity["activity_code"] for activity in applicable_control_activities
            ]

            for section in ["observations", "findings", "recommendations"]:
                if section in consolidated_summary and consolidated_summary[section]:
                    consolidated_summary[section] = [
                        item
                        for item in consolidated_summary[section]
                        if item.get("activity_code") in applicable_activity_codes
                    ]

    # Get consolidated test summary from database
    consolidated_test_summary = None
    consolidated_test_record = (
        ConsolidatedTestSummary.query.filter_by(clause_id=clause_id)
        .order_by(ConsolidatedTestSummary.generated_at.desc())
        .first()
    )

    if consolidated_test_record:
        try:
            consolidated_test_summary = json.loads(
                consolidated_test_record.consolidated_summary
            )
        except (json.JSONDecodeError, TypeError):
            consolidated_test_summary = {
                "consolidated_summary": consolidated_test_record.consolidated_summary,
                "key_testing_areas": [],
                "walkthrough_approach": "",
                "sampling_methodology": "",
            }

    # Get consolidated observation summary from database
    consolidated_observation_summary = None
    consolidated_observation_record = (
        ConsolidatedObservationSummary.query.filter_by(clause_id=clause_id)
        .order_by(ConsolidatedObservationSummary.generated_at.desc())
        .first()
    )

    if consolidated_observation_record:
        try:
            consolidated_observation_summary = json.loads(
                consolidated_observation_record.consolidated_observation
            )
        except (json.JSONDecodeError, TypeError):
            consolidated_observation_summary = {
                "consolidated_summary": consolidated_observation_record.consolidated_observation,
                "key_observations": [],
                "common_patterns": [],
                "risk_areas": [],
                "improvement_opportunities": [],
            }

    # Get the LATEST consolidated findings summary
    consolidated_findings_summary = None
    findings_data = (
        ConsolidatedFindingsSummary.query.filter_by(clause_id=clause_id)
        .order_by(ConsolidatedFindingsSummary.created_at.desc())
        .first()
    )

    if findings_data and findings_data.consolidated_findings:
        try:
            consolidated_findings_summary = json.loads(
                findings_data.consolidated_findings
            )
        except json.JSONDecodeError:
            consolidated_findings_summary = None
            logger.error(
                f"Error parsing consolidated findings JSON for clause_id={clause_id}"
            )

    # Get the LATEST consolidated recommendations summary
    consolidated_recommendations_summary = None
    recommendations_data = (
        ConsolidatedRecommendationsSummary.query.filter_by(clause_id=clause_id)
        .order_by(ConsolidatedRecommendationsSummary.updated_at.desc())
        .first()
    )

    if recommendations_data and recommendations_data.consolidated_recommendations:
        try:
            consolidated_recommendations_summary = json.loads(
                recommendations_data.consolidated_recommendations
            )
        except json.JSONDecodeError:
            consolidated_recommendations_summary = None
            logger.error(
                f"Error parsing consolidated recommendations JSON for clause_id={clause_id}"
            )

    assessment_status = (
        clause.assessment_status
        if hasattr(clause, "assessment_status")
        else "To Be Assessed"
    )

    # Debug: Print final clause_status_info to verify
    logger.info(f"✅ Final clause_status_info: {clause_status_info}")

    # ============== CHECK IF ALL ACTIVITIES ARE EVALUATED ==============
    # An activity is considered "evaluated" if it has a compliant_status
    # that is NOT "To be Assessed" (i.e., Compliant, Partially Compliant, or Non-Compliant)
    all_activities_evaluated = True
    evaluated_count = 0
    not_evaluated_count = 0

    for activity in applicable_control_activities:
        status = activity.get("compliant_status", "To be Assessed")
        if status in ["Compliant", "Partially Compliant", "Non-Compliant"]:
            evaluated_count += 1
        else:
            all_activities_evaluated = False
            not_evaluated_count += 1

    logger.info(
        f"📊 Evaluation status: {evaluated_count}/{len(applicable_control_activities)} activities evaluated"
    )
    
    # Add this line before render_template
    current_time = datetime.utcnow()

    # Fetch project_checklist for EVE inquiry panel
    project_checklist = None
    try:
        from app.models.eve_models import ProjectChecklist
        # Get first control activity for this clause
        pca_ids = [pca.id for pca in project_compliance_activities]
        if pca_ids:
            pca_control = db.session.query(ProjectControlActivity).filter(
                ProjectControlActivity.project_compliance_activity_id.in_(pca_ids)
            ).first()
            if pca_control:
                project_checklist = ProjectChecklist.query.filter_by(
                    project_control_activity_id=pca_control.id
                ).first()
    except Exception as pce:
        logger.warning(f"Could not fetch project_checklist: {pce}")
        project_checklist = None

    return render_template(
        "dashboards/auditor/clause_test_steps.html",
        project=project,
        clause=clause,
        all_evidences=all_evidences,
        all_control_activities=sorted_all_control_activities,
        applicable_control_activities=sorted_applicable_control_activities,
        clause_status_info=clause_status_info,
        consolidated_summary=consolidated_summary,
        consolidated_summary_record=consolidated_summary_record,
        consolidated_test_summary=consolidated_test_summary,
        consolidated_observation_summary=consolidated_observation_summary,
        consolidated_findings_summary=consolidated_findings_summary,
        consolidated_recommendations_summary=consolidated_recommendations_summary,
        assessment_status=assessment_status,
        total_evidence_count=total_evidence_count,
        actual_evidence_files_count=actual_evidence_files_count,  
        evidence_files_details=evidence_files_details,  
        # Add these new variables
        # NEW: Activity-based evidence variables
        activities_with_evidence=activities_with_evidence,
        total_applicable_activities_count=total_applicable_activities_count,
        activities_evidence_percentage=activities_evidence_percentage,
        activities_evidence_color_class=activities_evidence_color_class,
        activities_evidence_bg_class=activities_evidence_bg_class,
        activities_evidence_border_class=activities_evidence_border_class,
        activities_evidence_progress_class=activities_evidence_progress_class,
        # Add these new variables
        all_activities_evaluated=all_activities_evaluated,
        evaluated_activities_count=evaluated_count,
        total_applicable_activities=len(applicable_control_activities),
        overall_severity_level=overall_severity_level,
        severity_details=severity_details,
        severity_counts=severity_counts,
        highest_severity_score=highest_severity_score,
        current_time=current_time,
        project_checklist_id=project_checklist.id if project_checklist else None,
    )


@audit_bp.route("/clause/<int:clause_id>/evaluation-progress")
@login_required
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def clause_evaluation_progress(clause_id):
    """Check how many applicable activities have been evaluated"""
    try:
        # Get applicable compliance activities
        compliance_activities = ProjectComplianceActivity.query.filter_by(
            project_clause_id=clause_id, applicability=True
        ).all()

        compliance_activity_ids = [ca.id for ca in compliance_activities]

        # Get control activities
        control_activities = ProjectControlActivity.query.filter(
            ProjectControlActivity.project_compliance_activity_id.in_(
                compliance_activity_ids
            )
        ).all()

        total = len(control_activities)
        evaluated = sum(
            1
            for activity in control_activities
            if activity.compliant_status
            in ["Compliant", "Partially Compliant", "Non-Compliant"]
        )

        return jsonify(
            {
                "success": True,
                "total_count": total,
                "evaluated_count": evaluated,
                "all_evaluated": total == evaluated,
            }
        )

    except Exception as e:
        logger.error(f"Error checking evaluation progress: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


def get_current_user_id():
    """
    Get the current user ID from your authentication system.
    Adjust based on how you handle user authentication.
    """

    if current_user.is_authenticated:
        return current_user.id

    return None


@audit_bp.route("/clause/<int:clause_id>/close-assessment", methods=["POST"])
@login_required
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def close_clause_assessment(clause_id):
    """
    Close assessment for a clause, marking it as completed.
    """
    try:
        # Get the clause
        clause = ProjectClause.query.get_or_404(clause_id)

        # Check if report was generated
        if current_user.free_report_used:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Editing disabled - Report already generated",
                    }
                ),
                400,
            )

        # Check if compliance status is still "To be Assessed"
        if clause.overall_compliance_status == "To be Assessed":
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Cannot close assessment while compliance status is 'To be Assessed'",
                    }
                ),
                400,
            )

        # Update assessment status to "Completed"
        # You might want to create a new field in ProjectClause for assessment_status
        # For now, let's assume we're adding a new field called `assessment_status`

        # First, check if the field exists (you'll need to add this to your model)
        # Add this to your ProjectClause model:
        # assessment_status = db.Column(db.String(50), default="In Progress")

        # Update assessment status
        clause.assessment_status = "Completed"
        clause.assessment_closed_at = db.func.current_timestamp()
        clause.assessment_closed_by = current_user.id

        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": "Assessment closed successfully",
                "assessment_status": "Completed",
            }
        )

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error closing assessment for clause {clause_id}: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


def get_assessment_status_display_info(status):
    """Return CSS classes and display text for assessment status."""
    status_map = {
        "In Progress": {
            "text": "In Progress",
            "css_class": "bg-yellow-100 text-yellow-800 border border-yellow-200",
        },
        "Completed": {
            "text": "Completed",
            "css_class": "bg-green-100 text-green-800 border border-green-200",
        },
    }

    return status_map.get(
        status,
        {
            "text": "In Progress",
            "css_class": "bg-gray-100 text-gray-800 border border-gray-200",
        },
    )


@audit_bp.route("/clause/<int:clause_id>/update-compliance-status", methods=["POST"])
@login_required
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def update_clause_compliance_status(clause_id):
    """
    Update the overall compliance status for a clause.
    """
    try:
        data = request.get_json()
        new_status = data.get("status")

        if not new_status:
            return jsonify({"success": False, "error": "No status provided"}), 400

        # Validate status
        valid_statuses = [
            "Compliant",
            "Partially Compliant",
            "Non-Compliant",
            "To be Assessed",
        ]
        if new_status not in valid_statuses:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
                    }
                ),
                400,
            )

        # Get the clause
        clause = ProjectClause.query.get_or_404(clause_id)

        # Check if the field exists (for backward compatibility)
        if not hasattr(clause, "overall_compliance_status"):
            # If field doesn't exist yet, we need to handle it differently
            # You might want to add the field dynamically or show an error
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Database schema needs to be updated. Please run migrations.",
                    }
                ),
                500,
            )

        # Update the clause's overall compliance status
        clause.overall_compliance_status = new_status
        clause.updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": f"Compliance status updated to {new_status}",
                "new_status": new_status,
                "css_class": get_status_css_class(new_status),
            }
        )

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating clause compliance status: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


def get_status_css_class(status):
    """Helper function to get CSS class for status."""
    status_classes = {
        "Compliant": "bg-green-100 text-green-800 border border-green-300",
        "Partially Compliant": "bg-yellow-100 text-yellow-800 border border-yellow-300",
        "Non-Compliant": "bg-red-100 text-red-800 border border-red-300",
        "To be Assessed": "bg-gray-100 text-gray-800 border border-gray-300",
    }
    return status_classes.get(
        status, "bg-gray-100 text-gray-800 border border-gray-300"
    )


@audit_bp.route("/clause/<int:clause_id>/reset-compliance-status", methods=["POST"])
@login_required
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def reset_clause_compliance_status(clause_id):
    """
    Reset the overall compliance status to be calculated from control activities.
    """
    try:
        # Get the clause
        clause = ProjectClause.query.get_or_404(clause_id)

        # Check if field exists
        if not hasattr(clause, "overall_compliance_status"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Database schema needs to be updated. Please run migrations.",
                    }
                ),
                500,
            )

        # Calculate the status from control activities
        calculated_status_info = calculate_clause_compliance_status(clause_id)

        # If it was manually set before, reset it to calculated
        clause.overall_compliance_status = "To be Assessed"  # Reset to default
        clause.updated_at = datetime.utcnow()

        db.session.commit()

        # Now calculate fresh status
        fresh_status_info = calculate_clause_compliance_status(clause_id)

        return jsonify(
            {
                "success": True,
                "message": f"Compliance status reset to calculated value: {fresh_status_info['text']}",
                "new_status": fresh_status_info["text"],
                "css_class": fresh_status_info["css_class"],
                "is_manual": False,
            }
        )

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error resetting clause compliance status: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@audit_bp.route(
    "/clause/<int:clause_id>/generate_consolidated_summary", methods=["POST"]
)
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def generate_consolidated_summary(clause_id):
    """
    Generate consolidated bullet points for findings and recommendations only.
    """
    try:
        # Get the clause and all control activities
        clause = ProjectClause.query.get_or_404(clause_id)
        current_user_id = get_current_user_id()

        # Get all applicable control activities for this clause
        project_compliance_activities = ProjectComplianceActivity.query.filter_by(
            project_clause_id=clause_id, applicability=True
        ).all()

        all_control_activities = []
        for pca in project_compliance_activities:
            control_activities = ProjectControlActivity.query.filter_by(
                project_compliance_activity_id=pca.id
            ).all()
            all_control_activities.extend(control_activities)

        if not all_control_activities:
            flash("No control activities found for this clause.", "warning")
            return redirect(url_for("audit.clause_test_steps", clause_id=clause_id))

        # Prepare data for LLM processing
        activities_data = []
        for activity in all_control_activities:
            activity_data = {
                "activity_code": activity.activity_code,
                "activity_name": activity.activity_name,
                "compliant_status": activity.compliant_status or "Not Assessed",
                "observation": activity.auditor_observation or "No observation",
                "findings": activity.findings or "No findings",
                "recommendations": activity.recommendations or "No recommendations",
            }
            activities_data.append(activity_data)

        # Generate consolidated summaries using LLM (only findings and recommendations)
        consolidated_data = generate_consolidated_bullet_points(
            activities_data, clause.clause_no
        )

        # Add metadata
        consolidated_data["metadata"] = {
            "clause_id": clause_id,
            "clause_no": clause.clause_no,
            "total_activities": len(all_control_activities),
            "generated_at": datetime.utcnow().isoformat(),
            "generated_by": current_user_id,
        }

        # Save to database
        existing_summary = ClauseConsolidatedSummary.query.filter_by(
            clause_id=clause_id
        ).first()

        if existing_summary:
            # Preserve existing observation summary if it exists
            if "observation_summary" in existing_summary.consolidated_data:
                consolidated_data["observation_summary"] = (
                    existing_summary.consolidated_data["observation_summary"]
                )

            existing_summary.consolidated_data = consolidated_data
            existing_summary.updated_at = datetime.utcnow()
            existing_summary.created_by = current_user_id
            action = "updated"
        else:
            new_summary = ClauseConsolidatedSummary(
                clause_id=clause_id,
                consolidated_data=consolidated_data,
                created_by=current_user_id,
            )
            db.session.add(new_summary)
            action = "created"

        db.session.commit()
        flash(
            f"Consolidated findings and recommendations {action} successfully!",
            "success",
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error generating consolidated summary: {str(e)}")
        flash("Error generating consolidated summaries.", "danger")

    return redirect(url_for("audit.clause_test_steps", clause_id=clause_id))


def generate_consolidated_bullet_points(activities_data, clause_no):
    """
    Generate consolidated bullet points using LLM for observations, findings, and recommendations.
    """
    try:
        prompt = create_consolidation_prompt(activities_data, clause_no)
        response = generate_chat_output(prompt)

        # Parse the JSON response
        if "```json" in response:
            json_start = response.find("{", response.find("```json"))
            json_end = response.rfind("}") + 1
            if json_start != -1 and json_end != -1:
                response = response[json_start:json_end]
        elif "```" in response:
            json_start = response.find("{", response.find("```"))
            json_end = response.rfind("}") + 1
            if json_start != -1 and json_end != -1:
                response = response[json_start:json_end]

        consolidated_data = json.loads(response)
        return consolidated_data

    except Exception as e:
        current_app.logger.error(
            f"Error in generate_consolidated_bullet_points: {str(e)}"
        )
        # Return fallback data
        return create_fallback_consolidation(activities_data)


def create_fallback_consolidation(activities_data):
    """
    Create fallback consolidation data if LLM fails.
    """

    findings = []
    recommendations = []

    for activity in activities_data:
        # Create simple fallback summaries
        finding_text = (
            activity["findings"][:100] + "..."
            if len(activity["findings"]) > 100
            else activity["findings"]
        )
        rec_text = (
            activity["recommendations"][:100] + "..."
            if len(activity["recommendations"]) > 100
            else activity["recommendations"]
        )

        findings.append(
            {
                "activity_code": activity["activity_code"],
                "activity_name": activity["activity_name"],
                "bullet_point": finding_text,
            }
        )

        recommendations.append(
            {
                "activity_code": activity["activity_code"],
                "activity_name": activity["activity_name"],
                "bullet_point": rec_text,
            }
        )

    return {
        "findings": findings,
        "recommendations": recommendations,
    }


@audit_bp.route("/update_consolidated_bullet", methods=["POST"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def update_consolidated_bullet():
    """
    Update a specific bullet point in the consolidated summary.
    """
    try:
        data = request.get_json()
        clause_id = data.get("clause_id")
        bullet_type = data.get(
            "type"
        )  # 'observations', 'findings', or 'recommendations'
        index = data.get("index")
        activity_code = data.get("activity_code")
        new_text = data.get("new_text")

        print(f"=== UPDATE DEBUG ===")
        print(f"clause_id: {clause_id}")
        print(f"bullet_type: {bullet_type}")
        print(f"index: {index}")
        print(f"activity_code: {activity_code}")
        print(f"new_text: {new_text}")

        if not all(
            [clause_id, bullet_type, index is not None, activity_code, new_text]
        ):
            return jsonify({"success": False, "error": "Missing required fields"}), 400

        # Get the consolidated summary from database
        consolidated_summary = ClauseConsolidatedSummary.query.filter_by(
            clause_id=clause_id
        ).first()

        if not consolidated_summary:
            print("Consolidated summary not found")
            return (
                jsonify({"success": False, "error": "Consolidated summary not found"}),
                404,
            )

        # Update the specific bullet point
        consolidated_data = consolidated_summary.consolidated_data

        print(
            f"Before update - consolidated_data keys: {list(consolidated_data.keys())}"
        )
        print(
            f"Before update - {bullet_type} length: {len(consolidated_data.get(bullet_type, []))}"
        )

        if bullet_type in consolidated_data:
            print(
                f"Found {bullet_type} with {len(consolidated_data[bullet_type])} items"
            )

            # Convert index to integer and check bounds
            index_int = int(index)
            if index_int < len(consolidated_data[bullet_type]):
                print(f"Updating item at index {index_int}")
                print(f"Before update: {consolidated_data[bullet_type][index_int]}")

                # Update the bullet point text
                consolidated_data[bullet_type][index_int]["bullet_point"] = new_text

                print(
                    f"After update in memory: {consolidated_data[bullet_type][index_int]}"
                )

                # FIX: Force SQLAlchemy to detect the change
                # Method 1: Mark the field as modified
                from sqlalchemy.orm.attributes import flag_modified

                flag_modified(consolidated_summary, "consolidated_data")

                # Method 2: Reassign the entire JSON (alternative approach)
                # consolidated_summary.consolidated_data = consolidated_data

                consolidated_summary.updated_at = datetime.utcnow()

                # Commit to database
                print("About to commit changes to database...")
                db.session.commit()

                # Refresh and verify
                db.session.refresh(consolidated_summary)
                print(
                    f"After commit and refresh - {bullet_type}[{index_int}]: {consolidated_summary.consolidated_data[bullet_type][index_int]}"
                )

                print("Update successful!")
                return jsonify({"success": True})
            else:
                print(
                    f"Index {index_int} out of bounds for {bullet_type} (length: {len(consolidated_data[bullet_type])})"
                )
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Index {index} out of bounds for {bullet_type}",
                        }
                    ),
                    404,
                )
        else:
            print(f"Bullet type {bullet_type} not found in consolidated data")
            print(f"Available keys: {list(consolidated_data.keys())}")
            return (
                jsonify(
                    {"success": False, "error": f"Bullet type {bullet_type} not found"}
                ),
                404,
            )

    except Exception as e:
        db.session.rollback()
        print(f"Error in update_consolidated_bullet: {str(e)}")
        import traceback

        print(f"Traceback: {traceback.format_exc()}")
        current_app.logger.error(f"Error updating consolidated bullet: {str(e)}")
        return jsonify({"success": False, "error": "Internal server error"}), 500


def calculate_clause_compliance_status(clause_id):
    """
    Calculate overall compliance status and consolidate observations, findings,
    and recommendations for only APPLICABLE activities in a clause.
    """
    try:
        # Get the clause
        clause = ProjectClause.query.get(clause_id)

        # Check for manually set status
        has_overall_status = hasattr(clause, "overall_compliance_status")
        if (
            has_overall_status
            and clause.overall_compliance_status
            and clause.overall_compliance_status != "To be Assessed"
        ):
            # Return the manually set status
            return {
                "text": clause.overall_compliance_status,
                "css_class": get_status_css_class(clause.overall_compliance_status),
                "is_manual": True,
                "details": "Manually set compliance status",
                # Statistics will be added separately in the route
            }

        # Get all applicable control activities
        applicable_activities = []
        for compliance_activity in clause.project_compliance_activities:
            if getattr(compliance_activity, "applicability", True):
                applicable_activities.extend(
                    compliance_activity.project_control_activities
                )

        # Count statuses
        status_counts = {
            "total": len(applicable_activities),
            "Compliant": 0,
            "Partially Compliant": 0,
            "Non-Compliant": 0,
            "Not Assessed": 0,
        }

        for activity in applicable_activities:
            status = getattr(activity, "compliant_status", None)

            if status == "Compliant":
                status_counts["Compliant"] += 1
            elif status == "Partially Compliant":
                status_counts["Partially Compliant"] += 1
            elif status == "Non-Compliant":
                status_counts["Non-Compliant"] += 1
            else:
                status_counts["Not Assessed"] += 1

        # Determine overall status
        if status_counts["total"] == 0:
            overall_status = "To be Assessed"
            details = "No activities found for this clause"
        elif status_counts["Not Assessed"] > 0:
            overall_status = "To be Assessed"
            details = f"{status_counts['Not Assessed']} of {status_counts['total']} activities need assessment"
        elif status_counts["Non-Compliant"] > 0:
            overall_status = "Non-Compliant"
            details = f"{status_counts['Non-Compliant']} non-compliant activities found"
        elif status_counts["Partially Compliant"] > 0:
            overall_status = "Partially Compliant"
            details = f"{status_counts['Partially Compliant']} partially compliant activities found"
        elif status_counts["Compliant"] == status_counts["total"]:
            overall_status = "Compliant"
            details = "All applicable activities are compliant"
        else:
            overall_status = "To be Assessed"
            details = "Status needs assessment"

        return {
            "text": overall_status,
            "css_class": get_status_css_class(overall_status),
            "details": details,
            "is_manual": False,
            # Statistics will be added in the route
        }

    except Exception as e:
        logger.error(f"Error calculating clause compliance status: {str(e)}")
        return {
            "text": "To be Assessed",
            "css_class": get_status_css_class("To be Assessed"),
            "details": f"Error: {str(e)}",
            "is_manual": False,
        }


def get_clause_statistics(clause_id):
    """
    Helper function to get statistics for a clause.
    """
    try:
        clause = ProjectClause.query.get(clause_id)
        if not clause:
            return {
                "total": 0,
                "Compliant": 0,
                "Partially Compliant": 0,
                "Non-Compliant": 0,
                "To Be Assessed": 0,
            }

        # Count activities
        total_activities = 0
        for compliance_activity in clause.project_compliance_activities:
            if getattr(compliance_activity, "applicability", True):
                total_activities += len(compliance_activity.project_control_activities)

        # Return default statistics (you might want to calculate actual statistics here)
        return {
            "total": total_activities,
            "Compliant": 0,
            "Partially Compliant": 0,
            "Non-Compliant": 0,
            "To Be Assessed": total_activities,  # Default to all "To Be Assessed"
        }
    except Exception as e:
        logger.error(f"Error getting clause statistics: {str(e)}")
        return {
            "total": 0,
            "Compliant": 0,
            "Partially Compliant": 0,
            "Non-Compliant": 0,
            "To Be Assessed": 0,
        }


@audit_bp.route(
    "/clause/<int:clause_id>/generate_observation_summary", methods=["POST"]
)
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def generate_observation_summary(clause_id):
    """
    Generate a consolidated observation summary for all activities in a clause.
    """
    try:
        # Get the clause and all control activities
        clause = ProjectClause.query.get_or_404(clause_id)

        # Get current user ID
        current_user_id = get_current_user_id()

        # Get all applicable control activities for this clause
        project_compliance_activities = ProjectComplianceActivity.query.filter_by(
            project_clause_id=clause_id, applicability=True
        ).all()

        all_control_activities = []
        for pca in project_compliance_activities:
            control_activities = ProjectControlActivity.query.filter_by(
                project_compliance_activity_id=pca.id
            ).all()
            all_control_activities.extend(control_activities)

        if not all_control_activities:
            flash("No applicable control activities found for this clause.", "warning")
            return redirect(url_for("audit.clause_test_steps", clause_id=clause_id))

        # Prepare data for LLM processing
        activities_data = []
        for activity in all_control_activities:
            activity_data = {
                "activity_code": activity.activity_code,
                "activity_name": activity.activity_name,
                "compliant_status": activity.compliant_status or "Not Assessed",
                "observation": activity.auditor_observation
                or "No observation recorded",
                "findings": activity.findings or "No findings",
                "recommendations": activity.recommendations or "No recommendations",
            }
            activities_data.append(activity_data)

        # Generate observation summary using LLM
        observation_summary = generate_observation_summary_llm(
            activities_data, clause.clause_no
        )

        # Debug print
        print(f"=== GENERATED OBSERVATION SUMMARY ===")
        print(f"Summary length: {len(observation_summary)}")
        print(f"First 200 chars: {observation_summary[:200]}...")
        print("=====================================")

        # Get or create consolidated summary record
        consolidated_summary = ClauseConsolidatedSummary.query.filter_by(
            clause_id=clause_id
        ).first()

        if consolidated_summary:
            # Ensure consolidated_data is a proper dictionary
            if consolidated_summary.consolidated_data is None:
                consolidated_summary.consolidated_data = {}

            # Update the observation summary - use dictionary assignment
            consolidated_data = consolidated_summary.consolidated_data
            consolidated_data["observation_summary"] = observation_summary
            consolidated_summary.consolidated_data = (
                consolidated_data  # Reassign to trigger change detection
            )
            consolidated_summary.updated_at = datetime.utcnow()
            consolidated_summary.created_by = current_user_id
            action = "updated"

            print(f"Updated existing record with observation_summary")
        else:
            # Create new record with proper structure
            consolidated_data = {
                "observation_summary": observation_summary,
                "findings": [],
                "recommendations": [],
            }
            consolidated_summary = ClauseConsolidatedSummary(
                clause_id=clause_id,
                consolidated_data=consolidated_data,
                created_by=current_user_id,
            )
            db.session.add(consolidated_summary)
            action = "created"

            print(f"Created new record with observation_summary")

        # Force SQLAlchemy to detect the change
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(consolidated_summary, "consolidated_data")

        db.session.commit()

        # Verify the save worked
        saved_record = ClauseConsolidatedSummary.query.filter_by(
            clause_id=clause_id
        ).first()
        if saved_record and saved_record.consolidated_data:
            print(
                f"Save verified - observation_summary in data: {'observation_summary' in saved_record.consolidated_data}"
            )
            if "observation_summary" in saved_record.consolidated_data:
                print(
                    f"Saved observation summary length: {len(saved_record.consolidated_data['observation_summary'])}"
                )

        flash(f"Observation summary {action} successfully!", "success")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error generating observation summary: {str(e)}")
        import traceback

        print(f"Error traceback: {traceback.format_exc()}")
        flash("Error generating observation summary.", "danger")

    return redirect(url_for("audit.clause_test_steps", clause_id=clause_id))


def generate_observation_summary_llm(activities_data, clause_no):
    """
    Generate a consolidated observation summary using LLM.
    """
    try:
        prompt = create_observation_summary_prompt(activities_data, clause_no)
        response = generate_chat_output(prompt)

        # Clean the response - remove any markdown code blocks
        if "```" in response:
            # Extract content between ``` if present
            lines = response.split("\n")
            content_lines = []
            in_code_block = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if not in_code_block:
                    content_lines.append(line)
            response = "\n".join(content_lines).strip()

        return response

    except Exception as e:
        current_app.logger.error(f"Error in generate_observation_summary_llm: {str(e)}")
        # Return fallback summary
        return create_fallback_observation_summary(activities_data)


def create_fallback_observation_summary(activities_data):
    """
    Create fallback observation summary if LLM fails.
    """
    compliant_count = sum(
        1
        for activity in activities_data
        if activity.get("compliant_status", "").lower() in ["compliant"]
    )
    partial_count = sum(
        1
        for activity in activities_data
        if activity.get("compliant_status", "").lower()
        in [
            "partially compliant",
            "partial compliant",
            "partially-compliant",
            "partial-compliant",
        ]
    )
    non_compliant_count = sum(
        1
        for activity in activities_data
        if activity.get("compliant_status", "").lower()
        in ["non compliant", "non-compliant", "not compliant", "not-compliant"]
    )

    total_activities = len(activities_data)

    summary = f"""Overall observation for {total_activities} activities reviewed:
- {compliant_count} activities found to be fully compliant
- {partial_count} activities with partial compliance
- {non_compliant_count} activities identified as non-compliant

Key observations across the activities include varying levels of control implementation and documentation completeness. Further detailed analysis is recommended for activities with partial or non-compliant status."""

    return summary


@audit_bp.route("/update_observation_summary", methods=["POST"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def update_observation_summary():
    """
    Update the consolidated observation summary for a clause.
    """
    try:
        data = request.get_json()
        clause_id = data.get("clause_id")
        new_summary = data.get("new_summary")

        print(f"=== OBSERVATION SUMMARY UPDATE DEBUG ===")
        print(f"clause_id: {clause_id}")
        print(f"new_summary: {new_summary}")

        if not clause_id or new_summary is None:
            return jsonify({"success": False, "error": "Missing required fields"}), 400

        # Get the consolidated summary from database
        consolidated_summary = ClauseConsolidatedSummary.query.filter_by(
            clause_id=clause_id
        ).first()

        if not consolidated_summary:
            print("Consolidated summary not found, creating new one")
            # Create new record if it doesn't exist
            consolidated_summary = ClauseConsolidatedSummary(
                clause_id=clause_id,
                consolidated_data={"observation_summary": new_summary},
                created_by=get_current_user_id(),
            )
            db.session.add(consolidated_summary)
        else:
            # Update existing record
            if not consolidated_summary.consolidated_data:
                consolidated_summary.consolidated_data = {}
            consolidated_summary.consolidated_data["observation_summary"] = new_summary
            consolidated_summary.updated_at = datetime.utcnow()

        db.session.commit()
        print("Observation summary update successful!")
        return jsonify({"success": True})

    except Exception as e:
        db.session.rollback()
        print(f"Error in update_observation_summary: {str(e)}")
        import traceback

        print(f"Traceback: {traceback.format_exc()}")
        current_app.logger.error(f"Error updating observation summary: {str(e)}")
        return jsonify({"success": False, "error": "Internal server error"}), 500


# consolidated test procedure summary section starts from here
@audit_bp.route("/generate_consolidated_test_procedure_route", methods=["POST"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def generate_consolidated_test_procedure_route():
    """Trigger consolidated test procedure generation"""
    try:
        clause_id = request.form.get("clause_id")

        if not clause_id:
            return jsonify({"success": False, "error": "Invalid clause ID"})

        # Debug: Check if project clause exists
        project_clause = ProjectClause.query.get(clause_id)
        if not project_clause:
            return jsonify({"success": False, "error": "Project clause not found"})

        # Debug: Check compliance activities count
        pca_count = ProjectComplianceActivity.query.filter_by(
            project_clause_id=clause_id
        ).count()
        logger.info(
            f"DEBUG: Found {pca_count} compliance activities for project_clause_id {clause_id}"
        )

        # Start the Celery task
        logger.info(
            f"DEBUG: Starting Celery task for test procedure for clause_id: {clause_id}"
        )
        task = generate_consolidated_test_procedure.delay(int(clause_id))

        return jsonify(
            {
                "success": True,
                "message": "Consolidated test procedure generation started!",
                "task_id": task.id,
                "clause_id": clause_id,
            }
        )

    except Exception as e:
        logger.error(f"Error in generate_consolidated_test_procedure_route: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@audit_bp.route("/get_consolidated_test_summary/<int:clause_id>", methods=["GET"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def get_consolidated_test_summary(clause_id):
    """Get consolidated test summary for a clause"""
    try:
        summary = (
            ConsolidatedTestSummary.query.filter_by(clause_id=clause_id)
            .order_by(ConsolidatedTestSummary.generated_at.desc())
            .first()
        )

        if summary:
            summary_data = json.loads(summary.consolidated_summary)
            return jsonify({"success": True, "summary": summary_data})
        else:
            return jsonify(
                {"success": False, "message": "No consolidated test summary found"}
            )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@audit_bp.route("/update_consolidated_test_summary", methods=["POST"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def update_consolidated_test_summary():
    """Update consolidated test summary after manual editing"""
    try:
        data = request.get_json()
        clause_id = data.get("clause_id")
        consolidated_summary = data.get("consolidated_summary")
        key_testing_areas = data.get("key_testing_areas", [])
        walkthrough_approach = data.get("walkthrough_approach")
        sampling_methodology = data.get("sampling_methodology")

        if not clause_id or not consolidated_summary:
            return jsonify(
                {
                    "success": False,
                    "error": "Clause ID and consolidated summary are required",
                }
            )

        # Find the existing consolidated test summary
        summary = ConsolidatedTestSummary.query.filter_by(clause_id=clause_id).first()

        if summary:
            # Update existing summary
            summary_data = {
                "consolidated_summary": consolidated_summary,
                "key_testing_areas": key_testing_areas,
                "walkthrough_approach": walkthrough_approach,
                "sampling_methodology": sampling_methodology,
                "generated_at": datetime.utcnow().isoformat(),
                "updated_manually": True,
            }

            summary.consolidated_summary = json.dumps(summary_data)
            summary.updated_at = datetime.utcnow()
            db.session.commit()

            return jsonify(
                {
                    "success": True,
                    "message": "Consolidated test procedure updated successfully",
                }
            )
        else:
            return jsonify(
                {"success": False, "error": "Consolidated test summary not found"}
            )

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating consolidated test summary: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@audit_bp.route("/check_test_procedure_task_status/<int:clause_id>")
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def check_test_procedure_task_status(clause_id):
    """Check if test procedure generation is complete and return the latest summary"""
    try:
        # Get the latest test procedure summary
        test_data = (
            ConsolidatedTestSummary.query.filter_by(clause_id=clause_id)
            .order_by(ConsolidatedTestSummary.updated_at.desc())
            .first()
        )

        if test_data and test_data.consolidated_summary:
            try:
                summary_data = json.loads(test_data.consolidated_summary)

                # Check if the summary was generated very recently (within last 2 minutes)
                generated_at = datetime.fromisoformat(
                    summary_data.get("generated_at", "")
                )
                time_diff = datetime.utcnow() - generated_at

                # If generated within last 2 minutes, consider it fresh
                if time_diff.total_seconds() < 120:  # 2 minutes
                    return jsonify(
                        {
                            "status": "completed",
                            "summary": summary_data,
                            "generated_at": summary_data.get("generated_at"),
                            "activities_processed": summary_data.get(
                                "activities_processed", 0
                            ),
                        }
                    )
                else:
                    # Summary exists but is old - might be from previous generation
                    return jsonify(
                        {
                            "status": "processing",
                            "message": "Generation in progress...",
                            "has_old_summary": True,
                        }
                    )

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.error(f"Error parsing test procedure summary: {str(e)}")
                return jsonify(
                    {"status": "processing", "message": "Processing your request..."}
                )

        # No summary found at all
        return jsonify(
            {"status": "processing", "message": "Starting generation process..."}
        )

    except Exception as e:
        logger.error(f"Error checking test procedure status: {str(e)}")
        return jsonify({"status": "error", "message": str(e)})


# consolidated observation summary  section starts from here
@audit_bp.route("/generate_consolidated_observation_route", methods=["POST"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def generate_consolidated_observation_route():
    """Trigger consolidated observation summary generation"""
    try:
        clause_id = request.form.get("clause_id")
        logger.info(
            f"DEBUG: Starting consolidated observation generation for clause_id: {clause_id}"
        )

        if not clause_id:
            return jsonify({"success": False, "error": "Invalid clause ID"})

        # Check if project clause exists
        project_clause = ProjectClause.query.get(clause_id)
        if not project_clause:
            return jsonify({"success": False, "error": "Project clause not found"})

        # Start the Celery task
        logger.info(
            f"DEBUG: Starting Celery task for observations for clause_id: {clause_id}"
        )
        task = generate_consolidated_observation_summary.delay(int(clause_id))

        return jsonify(
            {
                "success": True,
                "message": "Consolidated observation summary generation started!",
                "task_id": task.id,
                "clause_id": clause_id,
            }
        )

    except Exception as e:
        logger.error(
            f"Error in generate_consolidated_observation_route: {str(e)}", exc_info=True
        )
        return jsonify({"success": False, "error": str(e)}), 500


@audit_bp.route("/update_consolidated_observation_summary", methods=["POST"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def update_consolidated_observation_summary():
    """Update consolidated observation summary manually"""
    try:
        data = request.get_json()
        clause_id = data.get("clause_id")

        if not clause_id:
            return jsonify({"success": False, "error": "Clause ID is required"}), 400

        # Find the consolidated observation summary
        consolidated_observation = ConsolidatedObservationSummary.query.filter_by(
            clause_id=clause_id
        ).first()

        if not consolidated_observation:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Consolidated observation summary not found",
                    }
                ),
                404,
            )

        # Parse existing data
        try:
            existing_data = json.loads(
                consolidated_observation.consolidated_observation
            )
        except (json.JSONDecodeError, TypeError):
            existing_data = {}

        # Update with new data
        updated_data = {
            "consolidated_summary": data.get(
                "consolidated_summary", existing_data.get("consolidated_summary", "")
            ),
            "key_observations": data.get(
                "key_observations", existing_data.get("key_observations", [])
            ),
            "common_patterns": data.get(
                "common_patterns", existing_data.get("common_patterns", [])
            ),
            "risk_areas": data.get("risk_areas", existing_data.get("risk_areas", [])),
            "improvement_opportunities": data.get(
                "improvement_opportunities",
                existing_data.get("improvement_opportunities", []),
            ),
            "generated_at": existing_data.get(
                "generated_at", datetime.utcnow().isoformat()
            ),
            "activities_processed": existing_data.get("activities_processed", 0),
            "manually_updated": True,
            "last_updated": datetime.utcnow().isoformat(),
        }

        # Save updated data
        consolidated_observation.consolidated_observation = json.dumps(updated_data)
        consolidated_observation.updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify({"success": True})

    except Exception as e:
        logger.error(f"Error updating consolidated observation summary: {str(e)}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@audit_bp.route("/check_observation_task_status/<int:clause_id>")
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def check_observation_task_status(clause_id):
    """Check if observation generation is complete and return the latest summary"""
    try:
        # Get the latest observation summary
        observation_data = (
            ConsolidatedObservationSummary.query.filter_by(clause_id=clause_id)
            .order_by(ConsolidatedObservationSummary.updated_at.desc())
            .first()
        )

        if observation_data and observation_data.consolidated_observation:
            try:
                summary_data = json.loads(observation_data.consolidated_observation)

                # Check if the summary was generated very recently (within last 2 minutes)
                generated_at = datetime.fromisoformat(
                    summary_data.get("generated_at", "")
                )
                time_diff = datetime.utcnow() - generated_at

                # If generated within last 2 minutes, consider it fresh
                if time_diff.total_seconds() < 120:  # 2 minutes
                    return jsonify(
                        {
                            "status": "completed",
                            "summary": summary_data,
                            "generated_at": summary_data.get("generated_at"),
                            "activities_processed": summary_data.get(
                                "activities_processed", 0
                            ),
                        }
                    )
                else:
                    # Summary exists but is old - might be from previous generation
                    return jsonify(
                        {
                            "status": "processing",
                            "message": "Generation in progress...",
                            "has_old_summary": True,
                        }
                    )

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.error(f"Error parsing observation summary: {str(e)}")
                return jsonify(
                    {"status": "processing", "message": "Processing your request..."}
                )

        # No summary found at all
        return jsonify(
            {"status": "processing", "message": "Starting generation process..."}
        )

    except Exception as e:
        logger.error(f"Error checking observation status: {str(e)}")
        return jsonify({"status": "error", "message": str(e)})


# consolidated findings summary section starts from here
@audit_bp.route("/generate_consolidated_findings_route", methods=["POST"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def generate_consolidated_findings_route():
    """Trigger consolidated findings summary generation"""
    try:
        clause_id = request.form.get("clause_id")
        logger.info(
            f"DEBUG: Starting consolidated findings generation for clause_id: {clause_id}"
        )

        if not clause_id:
            return jsonify({"success": False, "error": "Invalid clause ID"})

        # Check if project clause exists
        project_clause = ProjectClause.query.get(clause_id)
        if not project_clause:
            return jsonify({"success": False, "error": "Project clause not found"})

        # Start the Celery task
        logger.info(
            f"DEBUG: Starting Celery task for findings for clause_id: {clause_id}"
        )
        task = generate_consolidated_findings_summary.delay(int(clause_id))

        return jsonify(
            {
                "success": True,
                "message": "Consolidated findings summary generation started!",
                "task_id": task.id,
                "clause_id": clause_id,
            }
        )

    except Exception as e:
        logger.error(
            f"Error in generate_consolidated_findings_route: {str(e)}", exc_info=True
        )
        return jsonify({"success": False, "error": str(e)}), 500


@audit_bp.route("/update_consolidated_findings_summary", methods=["POST"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def update_consolidated_findings_summary():
    """Update consolidated findings summary manually"""
    try:
        data = request.get_json()
        clause_id = data.get("clause_id")

        if not clause_id:
            return jsonify({"success": False, "error": "Clause ID is required"}), 400

        # Find the consolidated findings summary
        consolidated_findings = ConsolidatedFindingsSummary.query.filter_by(
            clause_id=clause_id
        ).first()

        if not consolidated_findings:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Consolidated findings summary not found",
                    }
                ),
                404,
            )

        # Parse existing data
        try:
            existing_data = json.loads(consolidated_findings.consolidated_findings)
        except (json.JSONDecodeError, TypeError):
            existing_data = {}

        # Update with new data - only bullet points list
        updated_data = {
            "consolidated_summary": data.get(
                "consolidated_summary", existing_data.get("consolidated_summary", [])
            ),
            "generated_at": existing_data.get(
                "generated_at", datetime.utcnow().isoformat()
            ),
            "activities_processed": existing_data.get("activities_processed", 0),
            "manually_updated": True,
            "last_updated": datetime.utcnow().isoformat(),
        }

        # Save updated data
        consolidated_findings.consolidated_findings = json.dumps(updated_data)
        consolidated_findings.updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify({"success": True})

    except Exception as e:
        logger.error(f"Error updating consolidated findings summary: {str(e)}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@audit_bp.route("/check_findings_task_status/<int:clause_id>")
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def check_findings_task_status(clause_id):
    """Check if findings generation is complete and return the latest summary"""
    try:
        # Get the latest findings summary
        findings_data = (
            ConsolidatedFindingsSummary.query.filter_by(clause_id=clause_id)
            .order_by(ConsolidatedFindingsSummary.updated_at.desc())
            .first()
        )

        if findings_data and findings_data.consolidated_findings:
            try:
                summary_data = json.loads(findings_data.consolidated_findings)

                # Check if the summary was generated very recently (within last 2 minutes)
                generated_at = datetime.fromisoformat(
                    summary_data.get("generated_at", "")
                )
                time_diff = datetime.utcnow() - generated_at

                # If generated within last 2 minutes, consider it fresh
                if time_diff.total_seconds() < 120:  # 2 minutes
                    return jsonify(
                        {
                            "status": "completed",
                            "summary": summary_data,
                            "generated_at": summary_data.get("generated_at"),
                            "activities_processed": summary_data.get(
                                "activities_processed", 0
                            ),
                        }
                    )
                else:
                    # Summary exists but is old - might be from previous generation
                    return jsonify(
                        {
                            "status": "processing",
                            "message": "Generation in progress...",
                            "has_old_summary": True,
                        }
                    )

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.error(f"Error parsing findings summary: {str(e)}")
                return jsonify(
                    {"status": "processing", "message": "Processing your request..."}
                )

        # No summary found at all
        return jsonify(
            {"status": "processing", "message": "Starting generation process..."}
        )

    except Exception as e:
        logger.error(f"Error checking findings status: {str(e)}")
        return jsonify({"status": "error", "message": str(e)})


@audit_bp.route("/get_latest_findings_summary/<int:clause_id>")
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def get_latest_findings_summary(clause_id):
    """Get the latest findings summary for a clause"""
    try:
        findings_data = (
            ConsolidatedFindingsSummary.query.filter_by(clause_id=clause_id)
            .order_by(ConsolidatedFindingsSummary.updated_at.desc())
            .first()
        )

        if findings_data and findings_data.consolidated_findings:
            summary_data = json.loads(findings_data.consolidated_findings)
            return jsonify({"status": "success", "summary": summary_data})
        else:
            return jsonify(
                {"status": "not_found", "message": "No findings summary available"}
            )

    except Exception as e:
        logger.error(f"Error getting findings summary: {str(e)}")
        return jsonify({"status": "error", "message": str(e)})


# consolidated recommendation summary section starts from here
@audit_bp.route("/generate_consolidated_recommendations_route", methods=["POST"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def generate_consolidated_recommendations_route():
    """Trigger consolidated recommendations summary generation"""
    try:
        clause_id = request.form.get("clause_id")
        logger.info(
            f"🚀 ROUTE: Starting consolidated recommendations generation for clause_id: {clause_id}"
        )

        if not clause_id:
            return jsonify({"success": False, "error": "Invalid clause ID"})

        # Check if project clause exists
        project_clause = ProjectClause.query.get(clause_id)
        if not project_clause:
            return jsonify({"success": False, "error": "Project clause not found"})

        # Start the Celery task
        logger.info(
            f"🎯 Starting Celery task for recommendations for clause_id: {clause_id}"
        )

        task = generate_consolidated_recommendations_summary.delay(int(clause_id))

        return jsonify(
            {
                "success": True,
                "message": "Consolidated recommendations summary generation started!",
                "task_id": task.id,
                "clause_id": clause_id,
            }
        )

    except Exception as e:
        logger.error(
            f"❌ Error in generate_consolidated_recommendations_route: {str(e)}",
            exc_info=True,
        )
        return jsonify({"success": False, "error": str(e)})


@audit_bp.route("/check_recommendations_task_status/<int:clause_id>")
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def check_recommendations_task_status(clause_id):
    """Check if recommendations generation is complete and return the latest summary"""
    try:
        # Get the latest recommendations summary
        recommendations_data = (
            ConsolidatedRecommendationsSummary.query.filter_by(clause_id=clause_id)
            .order_by(ConsolidatedRecommendationsSummary.updated_at.desc())
            .first()
        )

        if recommendations_data and recommendations_data.consolidated_recommendations:
            try:
                summary_data = json.loads(
                    recommendations_data.consolidated_recommendations
                )

                # Check if the summary was generated very recently (within last 5 minutes)
                generated_at = datetime.fromisoformat(
                    summary_data.get("generated_at", "")
                )
                time_diff = datetime.utcnow() - generated_at

                # If generated within last 5 minutes, consider it fresh
                if time_diff.total_seconds() < 300:  # 5 minutes
                    return jsonify(
                        {
                            "status": "completed",
                            "summary": summary_data,
                            "generated_at": summary_data.get("generated_at"),
                            "activities_processed": summary_data.get(
                                "activities_processed", 0
                            ),
                            "is_fresh": True,
                        }
                    )
                else:
                    # Summary exists but is old
                    return jsonify(
                        {
                            "status": "processing",
                            "message": "Generation in progress...",
                            "has_old_summary": True,
                        }
                    )

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.error(f"Error parsing recommendations summary: {str(e)}")
                return jsonify(
                    {"status": "processing", "message": "Processing your request..."}
                )

        # No summary found at all
        return jsonify(
            {"status": "processing", "message": "Starting generation process..."}
        )

    except Exception as e:
        logger.error(f"Error checking recommendations status: {str(e)}")
        return jsonify({"status": "error", "message": str(e)})


@audit_bp.route("/update_consolidated_recommendations_summary", methods=["POST"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def update_consolidated_recommendations_summary():
    """Update consolidated recommendations summary manually"""
    try:
        data = request.get_json()
        clause_id = data.get("clause_id")

        if not clause_id:
            return jsonify({"success": False, "error": "Clause ID is required"}), 400

        # Find the consolidated recommendations summary
        consolidated_recommendations = (
            ConsolidatedRecommendationsSummary.query.filter_by(
                clause_id=clause_id
            ).first()
        )

        if not consolidated_recommendations:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Consolidated recommendations summary not found",
                    }
                ),
                404,
            )

        # Parse existing data
        try:
            existing_data = json.loads(
                consolidated_recommendations.consolidated_recommendations
            )
        except (json.JSONDecodeError, TypeError):
            existing_data = {}

        # Update with new data - only bullet points list
        updated_data = {
            "consolidated_summary": data.get(
                "consolidated_summary", existing_data.get("consolidated_summary", [])
            ),
            "generated_at": existing_data.get(
                "generated_at", datetime.utcnow().isoformat()
            ),
            "activities_processed": existing_data.get("activities_processed", 0),
            "manually_updated": True,
            "last_updated": datetime.utcnow().isoformat(),
        }

        # Save updated data
        consolidated_recommendations.consolidated_recommendations = json.dumps(
            updated_data
        )
        consolidated_recommendations.updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify({"success": True})

    except Exception as e:
        logger.error(f"Error updating consolidated recommendations summary: {str(e)}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@audit_bp.route("/generate_all_consolidated_summaries", methods=["POST"])
def generate_all_consolidated_summaries_route():
    """Generate all consolidated summaries (test procedure, observations, findings, recommendations) for a clause"""
    try:
        clause_id = request.form.get("clause_id")
        if not clause_id:
            return jsonify({"success": False, "error": "Clause ID is required"}), 400

        # Convert to int
        clause_id = int(clause_id)

        # Start background tasks for each summary type
        from threading import Thread

        thread = Thread(target=generate_all_summaries_background, args=(clause_id,))
        thread.daemon = True
        thread.start()

        return jsonify({"success": True, "message": "Generation started"})
    except Exception as e:
        print(f"Error starting all summaries generation: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@audit_bp.route("/check_all_summaries_task_status/<int:clause_id>")
def check_all_summaries_task_status(clause_id):
    """Check the status of all summary generation tasks"""
    try:
        # Check if each summary exists
        test_procedure = ConsolidatedTestSummary.query.filter_by(
            clause_id=clause_id
        ).first()
        observations = ConsolidatedObservationSummary.query.filter_by(
            clause_id=clause_id
        ).first()
        findings = ConsolidatedFindingsSummary.query.filter_by(
            clause_id=clause_id
        ).first()
        recommendations = ConsolidatedRecommendationsSummary.query.filter_by(
            clause_id=clause_id
        ).first()

        # Create safe dictionary representations with CORRECT FIELD NAMES
        test_procedure_summary = None
        if test_procedure:
            try:
                summary_data = (
                    json.loads(test_procedure.consolidated_summary)
                    if test_procedure.consolidated_summary
                    else {}
                )
                test_procedure_summary = {
                    "consolidated_summary": summary_data.get(
                        "consolidated_summary", ""
                    ),
                    "key_testing_areas": summary_data.get("key_testing_areas", []),
                    "walkthrough_approach": summary_data.get(
                        "walkthrough_approach", ""
                    ),
                    "sampling_methodology": summary_data.get(
                        "sampling_methodology", ""
                    ),
                    "generated_at": summary_data.get("generated_at"),
                    "activities_processed": summary_data.get("activities_processed", 0),
                }
            except:
                test_procedure_summary = {
                    "consolidated_summary": "",
                    "key_testing_areas": [],
                    "walkthrough_approach": "",
                    "sampling_methodology": "",
                    "generated_at": None,
                    "activities_processed": 0,
                }

        observations_summary = None
        if observations:
            try:
                summary_data = (
                    json.loads(observations.consolidated_observation)
                    if observations.consolidated_observation
                    else {}
                )
                observations_summary = {
                    "consolidated_summary": summary_data.get(
                        "consolidated_summary", ""
                    ),
                    "key_observations": summary_data.get("key_observations", []),
                    "common_patterns": summary_data.get("common_patterns", []),
                    "risk_areas": summary_data.get("risk_areas", []),
                    "improvement_opportunities": summary_data.get(
                        "improvement_opportunities", []
                    ),
                    "generated_at": summary_data.get("generated_at"),
                    "activities_processed": summary_data.get("activities_processed", 0),
                }
            except:
                observations_summary = {
                    "consolidated_summary": "",
                    "key_observations": [],
                    "common_patterns": [],
                    "risk_areas": [],
                    "improvement_opportunities": [],
                    "generated_at": None,
                    "activities_processed": 0,
                }

        findings_summary = None
        if findings:
            try:
                summary_data = (
                    json.loads(findings.consolidated_findings)
                    if findings.consolidated_findings
                    else {}
                )
                findings_summary = {
                    "consolidated_summary": summary_data.get(
                        "consolidated_summary", []
                    ),
                    "generated_at": summary_data.get("generated_at"),
                    "activities_processed": summary_data.get("activities_processed", 0),
                }
            except:
                findings_summary = {
                    "consolidated_summary": [],
                    "generated_at": None,
                    "activities_processed": 0,
                }

        recommendations_summary = None
        if recommendations:
            try:
                summary_data = (
                    json.loads(recommendations.consolidated_recommendations)
                    if recommendations.consolidated_recommendations
                    else {}
                )
                recommendations_summary = {
                    "consolidated_summary": summary_data.get(
                        "consolidated_summary", []
                    ),
                    "generated_at": summary_data.get("generated_at"),
                    "activities_processed": summary_data.get("activities_processed", 0),
                }
            except:
                recommendations_summary = {
                    "consolidated_summary": [],
                    "generated_at": None,
                    "activities_processed": 0,
                }

        # Check if all are completed
        all_completed = all(
            [
                test_procedure is not None,
                observations is not None,
                findings is not None,
                recommendations is not None,
            ]
        )

        response_data = {
            "success": True,
            "test_procedure_completed": test_procedure is not None,
            "observations_completed": observations is not None,
            "findings_completed": findings is not None,
            "recommendations_completed": recommendations is not None,
            "all_completed": all_completed,
            "test_procedure_summary": test_procedure_summary,
            "observations_summary": observations_summary,
            "findings_summary": findings_summary,
            "recommendations_summary": recommendations_summary,
        }

        # If all are completed, log success
        if all_completed:
            print(f"✅ All summaries completed for clause {clause_id}")
            # Force all_completed to be true even if some are None? No, we check above

        return jsonify(response_data)

    except Exception as e:
        print(f"❌ Error checking all summaries status: {str(e)}")
        import traceback

        traceback.print_exc()
        return (
            jsonify(
                {
                    "success": False,
                    "error": str(e),
                    "test_procedure_completed": False,
                    "observations_completed": False,
                    "findings_completed": False,
                    "recommendations_completed": False,
                    "all_completed": False,
                }
            ),
            200,
        )  # Return 200 even on error to keep polling alive


def generate_all_summaries_background(clause_id):
    """Background task to generate all summaries"""
    try:
        print(f"Starting background generation of all summaries for clause {clause_id}")

        # Store generation start time in session or cache
        cache_key = f"summary_generation_{clause_id}"

        # Generate test procedure summary
        try:
            print(f"Generating test procedure for clause {clause_id}")
            result = generate_consolidated_test_procedure(clause_id)
            print(f"Test procedure generation result: {result}")
        except Exception as e:
            print(f"Error generating test procedure: {str(e)}")
            import traceback

            traceback.print_exc()

        # Generate observations summary
        try:
            print(f"Generating observations for clause {clause_id}")
            result = generate_consolidated_observation_summary(clause_id)
            print(f"Observations generation result: {result}")
        except Exception as e:
            print(f"Error generating observations: {str(e)}")
            import traceback

            traceback.print_exc()

        # Generate findings summary
        try:
            print(f"Generating findings for clause {clause_id}")
            result = generate_consolidated_findings_summary(clause_id)
            print(f"Findings generation result: {result}")
        except Exception as e:
            print(f"Error generating findings: {str(e)}")
            import traceback

            traceback.print_exc()

        # Generate recommendations summary
        try:
            print(f"Generating recommendations for clause {clause_id}")
            result = generate_consolidated_recommendations_summary(clause_id)
            print(f"Recommendations generation result: {result}")
        except Exception as e:
            print(f"Error generating recommendations: {str(e)}")
            import traceback

            traceback.print_exc()

        print(f"✅ Completed background generation for clause {clause_id}")

    except Exception as e:
        print(f"❌ Error in generate_all_summaries_background: {str(e)}")
        import traceback

        traceback.print_exc()


def check_evidence_needs_regeneration(project, evidence_record):
    """
    Check if consolidated evidence needs regeneration based on current applicable clauses
    """
    if not evidence_record or not evidence_record.consolidate_evidence:
        return False

    # Get current applicable clauses
    current_applicable_clauses = set()
    for p_guideline in project.project_guidelines:
        for p_clause in p_guideline.project_clauses:
            if p_clause.applicability:
                current_applicable_clauses.add(p_clause.clause_no)

    # Get clauses from existing evidence
    evidence_clauses = set()
    try:
        if isinstance(evidence_record.consolidate_evidence, str):
            evidence_data = json.loads(evidence_record.consolidate_evidence)
        else:
            evidence_data = evidence_record.consolidate_evidence

        for evidence_group in evidence_data.get("grouped_evidences", []):
            required_by = evidence_group.get("required_by", {})
            evidence_clauses.update(required_by.get("clause_nos", []))

    except (json.JSONDecodeError, AttributeError) as e:
        current_app.logger.error(f"Error checking evidence regeneration: {str(e)}")
        return True  # Regenerate if we can't parse existing evidence

    # Check if current applicable clauses match evidence clauses
    return current_applicable_clauses != evidence_clauses


def check_evidence_staleness(project, consolidated_evidence):
    """Check if evidence doesn't match current applicable clauses"""
    if not consolidated_evidence:
        return False

    # Get current applicable clause numbers
    current_clauses = set()
    for p_guideline in project.project_guidelines:
        for p_clause in p_guideline.project_clauses:
            if p_clause.applicability:
                current_clauses.add(p_clause.clause_no)

    # Get clauses from evidence
    evidence_clauses = set()
    for group in consolidated_evidence.get("grouped_evidences", []):
        evidence_clauses.update(group.get("required_by", {}).get("clause_nos", []))

    return current_clauses != evidence_clauses


@audit_bp.route("/project_details", methods=["GET"])
@role_required("COMPLIFYRE", "AUDITOR", "RE")
def get_project_details():
    add_to_breadcrumb(request.full_path, "Clause Details")
    project_id = request.args.get("project_id")
    project = Projects.query.get(project_id)

    if not project:
        flash("Project not found.", "danger")
        return redirect(url_for("audit.projects"))

    # Get consolidated evidence if exists
    consolidated_evidence = None
    evidence_record = ConsolidatedEvidence.query.filter_by(
        project_id=project.project_name
    ).first()

    # Check if evidence needs regeneration (compare current applicable clauses with evidence)
    evidence_needs_regeneration = check_evidence_needs_regeneration(
        project, evidence_record
    )

    if evidence_record and evidence_record.consolidate_evidence:
        if isinstance(evidence_record.consolidate_evidence, str):
            try:
                consolidated_evidence = json.loads(evidence_record.consolidate_evidence)
            except json.JSONDecodeError:
                current_app.logger.error(
                    f"Failed to parse consolidate_evidence as JSON for project {project.project_name}"
                )
                consolidated_evidence = None
        else:
            consolidated_evidence = evidence_record.consolidate_evidence

    # Process evidence files for template (if evidence exists)
    if consolidated_evidence and "grouped_evidences" in consolidated_evidence:
        for evidence_item in consolidated_evidence["grouped_evidences"]:
            evidence_ids = []
            if (
                "required_by" in evidence_item
                and "evidence" in evidence_item["required_by"]
            ):
                evidence_ids = [
                    e.get("evidence_id")
                    for e in evidence_item["required_by"]["evidence"]
                    if e.get("evidence_id")
                ]

            if evidence_ids:
                evidence_files = EvidenceFile.query.filter(
                    EvidenceFile.project_evidence_artifact_id.in_(evidence_ids)
                ).all()

                # Convert to dictionaries
                evidence_files_dict = []
                for file in evidence_files:
                    evidence_files_dict.append(
                        {
                            "id": file.id,
                            "file_name": file.file_name,
                            "stored_filename": file.stored_filename,
                            "file_path": file.file_path,
                            "content_type": file.content_type,
                            "file_size": file.file_size,
                            "uploaded_at": (
                                file.uploaded_at.isoformat()
                                if file.uploaded_at
                                else None
                            ),
                            "project_evidence_artifact_id": file.project_evidence_artifact_id,
                        }
                    )

                evidence_item["evidence_files"] = evidence_files_dict
            else:
                evidence_item["evidence_files"] = []

    # Check if evidence is stale (server-side)
    evidence_is_stale = check_evidence_staleness(project, consolidated_evidence)

    return render_template(
        "my_projects_new.html",
        project=project,
        project_name=project.project_name,
        consolidated_evidence=consolidated_evidence,
        evidence_is_stale=evidence_is_stale,  # Pass this to template
        evidence_needs_regeneration=evidence_needs_regeneration,
        now=datetime.now(),
    )


# ═══════════════════════════════════════════════════════════
# EVE INQUIRY APIs — Phase 3
# ═══════════════════════════════════════════════════════════

@audit_bp.route("/eve/inquiry/<int:project_checklist_id>", methods=["GET"])
@login_required
def get_eve_inquiries(project_checklist_id):
    """Fetch all inquiries for a project checklist."""
    try:
        from app.models.eve_models import EveInquiry

        status_filter = request.args.get("status")
        query = EveInquiry.query.filter_by(project_checklist_id=project_checklist_id)
        if status_filter:
            query = query.filter_by(status=status_filter)

        inquiries = query.order_by(EveInquiry.created_at.desc()).all()

        result = []
        for inq in inquiries:
            result.append({
                "id": inq.id,
                "checklist_item_id": inq.checklist_item_id,
                "contradiction_type": inq.contradiction_type,
                "severity": inq.severity,
                "evidence_a_claim": inq.evidence_a_claim,
                "evidence_b_claim": inq.evidence_b_claim,
                "inquiry_question": inq.inquiry_question,
                "suggested_evidence": inq.suggested_evidence,
                "auditor_response": inq.auditor_response,
                "re_evaluation_status": inq.re_evaluation_status,
                "re_evaluation_reason": inq.re_evaluation_reason,
                "re_evaluation_pass_condition_met": inq.re_evaluation_pass_condition_met,
                "status": inq.status,
                "resolution_note": inq.resolution_note,
                "escalation_reason": inq.escalation_reason,
                "created_at": inq.created_at.isoformat() if inq.created_at else None,
                "responded_at": inq.responded_at.isoformat() if inq.responded_at else None,
                "resolved_at": inq.resolved_at.isoformat() if inq.resolved_at else None,
            })

        pending = sum(1 for r in result if r["status"] == "PENDING_INQUIRY")
        responded = sum(1 for r in result if r["status"] == "RESPONDED")
        resolved = sum(1 for r in result if r["status"] == "RESOLVED")
        escalated = sum(1 for r in result if r["status"] == "ESCALATED_TO_FINDING")

        return jsonify({
            "status": "success",
            "project_checklist_id": project_checklist_id,
            "total": len(result),
            "counts": {
                "pending": pending,
                "responded": responded,
                "resolved": resolved,
                "escalated": escalated,
            },
            "inquiries": result,
        })

    except Exception as e:
        logger.exception(f"Error fetching inquiries for checklist {project_checklist_id}")
        return jsonify({"status": "error", "message": str(e)}), 500


@audit_bp.route("/eve/inquiry/<int:inquiry_id>/respond", methods=["POST"])
@login_required
def respond_eve_inquiry(inquiry_id):
    """Auditor responds to an inquiry."""
    try:
        from app.models.eve_models import EveInquiry
        from datetime import datetime

        inquiry = EveInquiry.query.get(inquiry_id)
        if not inquiry:
            return jsonify({"status": "error", "message": "Inquiry not found"}), 404

        if inquiry.status not in ("PENDING_INQUIRY", "RESPONDED"):
            return jsonify({"status": "error", "message": f"Cannot respond to inquiry with status: {inquiry.status}"}), 400

        data = request.get_json() or {}
        response_text = data.get("response", "").strip()
        if not response_text:
            return jsonify({"status": "error", "message": "Response text is required"}), 400

        inquiry.auditor_response = response_text
        inquiry.status = "RESPONDED"
        inquiry.responded_at = datetime.utcnow()
        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Response submitted successfully",
            "inquiry_id": inquiry_id,
            "new_status": inquiry.status,
        })

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error responding to inquiry {inquiry_id}")
        return jsonify({"status": "error", "message": str(e)}), 500


@audit_bp.route("/eve/inquiry/<int:inquiry_id>/re-evaluate", methods=["POST"])
@login_required
def re_evaluate_eve_inquiry(inquiry_id):
    """Trigger re-evaluation after auditor response."""
    try:
        from app.models.eve_models import EveInquiry
        from app.models.eve_models import ProjectChecklist
        from datetime import datetime
        import json as json_lib

        inquiry = EveInquiry.query.get(inquiry_id)
        if not inquiry:
            return jsonify({"status": "error", "message": "Inquiry not found"}), 404

        if inquiry.status != "RESPONDED":
            return jsonify({"status": "error", "message": "Inquiry must be in RESPONDED status before re-evaluation"}), 400

        inquiry.status = "RE_EVALUATING"
        db.session.commit()

        # Get checklist item details
        project_checklist = ProjectChecklist.query.get(inquiry.project_checklist_id)
        if not project_checklist:
            inquiry.status = "RESPONDED"
            db.session.commit()
            return jsonify({"status": "error", "message": "Project checklist not found"}), 404

        checklist_items = project_checklist.get_checklist_items()
        target_item = next((item for item in checklist_items if item.get("id") == inquiry.checklist_item_id), None)

        if not target_item:
            inquiry.status = "RESPONDED"
            db.session.commit()
            return jsonify({"status": "error", "message": "Checklist item not found"}), 404

        # Build re-evaluation prompt
        re_eval_prompt = f"""You are an Audit Evidence Re-evaluation Engine.

CONTEXT:
A contradiction was detected and an inquiry was raised.
The auditor has responded with clarification.

INQUIRY DETAILS:
- Checklist Item: {inquiry.checklist_item_id}
- Contradiction Type: {inquiry.contradiction_type}
- Original Issue: {inquiry.inquiry_question}
- Evidence A Claim: {inquiry.evidence_a_claim}
- Evidence B Claim: {inquiry.evidence_b_claim}

AUDITOR CLARIFICATION:
{inquiry.auditor_response}

CHECKLIST ITEM REQUIREMENT:
{json_lib.dumps(target_item, indent=2)}

TASK:
Re-evaluate whether the CHECKLIST REQUIREMENT is satisfied.

CRITICAL RULES:
1. The contradiction is now clarified — do NOT re-evaluate the contradiction
2. Evaluate SOLELY whether the PASS CONDITION is satisfied
3. Auditor clarification is CONTEXT — NOT independent evidence
4. No supporting evidence satisfying pass_condition = NO
5. Partial evidence = PARTIAL
6. Pass condition fully met = YES

Return ONLY valid JSON:
{{
  "checklist_item_id": "{inquiry.checklist_item_id}",
  "re_evaluation_status": "YES | NO | PARTIAL | NEEDS_REVIEW",
  "pass_condition_met": true,
  "reasoning": "Explanation of why pass/fail",
  "evidence_gaps": "What evidence is still missing",
  "recommended_action": "RESOLVE_PASS | RESOLVE_PARTIAL | ESCALATE_TO_FINDING"
}}"""

        from app import client as openai_client
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an audit evidence re-evaluation engine. Return only valid JSON."},
                {"role": "user", "content": re_eval_prompt}
            ],
            response_format={"type": "json_object"}
        )

        re_eval_result = json_lib.loads(response.choices[0].message.content)

        inquiry.re_evaluation_status = re_eval_result.get("re_evaluation_status", "NEEDS_REVIEW")
        inquiry.re_evaluation_reason = re_eval_result.get("reasoning", "")
        inquiry.re_evaluation_pass_condition_met = re_eval_result.get("pass_condition_met", False)
        inquiry.re_evaluated_at = datetime.utcnow()

        recommended = re_eval_result.get("recommended_action", "ESCALATE_TO_FINDING")
        if recommended in ("RESOLVE_PASS", "RESOLVE_PARTIAL"):
            inquiry.status = "RESOLVED"
            inquiry.resolution_note = f"Re-evaluated: {inquiry.re_evaluation_status} — {inquiry.re_evaluation_reason}"
            inquiry.resolved_at = datetime.utcnow()
            inquiry.resolved_by = current_user.id
        else:
            inquiry.status = "RESPONDED"

        db.session.commit()

        return jsonify({
            "status": "success",
            "inquiry_id": inquiry_id,
            "re_evaluation_status": inquiry.re_evaluation_status,
            "pass_condition_met": inquiry.re_evaluation_pass_condition_met,
            "reasoning": inquiry.re_evaluation_reason,
            "recommended_action": recommended,
            "new_inquiry_status": inquiry.status,
        })

    except Exception as e:
        db.session.rollback()
        try:
            inquiry.status = "RESPONDED"
            db.session.commit()
        except Exception:
            pass
        logger.exception(f"Error re-evaluating inquiry {inquiry_id}")
        return jsonify({"status": "error", "message": str(e)}), 500


@audit_bp.route("/eve/inquiry/<int:inquiry_id>/resolve", methods=["POST"])
@login_required
def resolve_eve_inquiry(inquiry_id):
    """Manually mark inquiry as resolved."""
    try:
        from app.models.eve_models import EveInquiry, EveAssuranceState
        from datetime import datetime

        inquiry = EveInquiry.query.get(inquiry_id)
        if not inquiry:
            return jsonify({"status": "error", "message": "Inquiry not found"}), 404

        if inquiry.status == "ESCALATED_TO_FINDING":
            return jsonify({"status": "error", "message": "Cannot resolve an escalated inquiry"}), 400

        data = request.get_json() or {}
        resolution_note = data.get("resolution_note", "").strip()

        inquiry.status = "RESOLVED"
        inquiry.resolution_note = resolution_note
        inquiry.resolved_at = datetime.utcnow()
        inquiry.resolved_by = current_user.id

        assurance = EveAssuranceState.query.filter_by(
            project_checklist_id=inquiry.project_checklist_id
        ).first()
        if assurance:
            assurance.resolved_inquiry_count = (assurance.resolved_inquiry_count or 0) + 1
            assurance.last_updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Inquiry resolved successfully",
            "inquiry_id": inquiry_id,
            "new_status": inquiry.status,
        })

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error resolving inquiry {inquiry_id}")
        return jsonify({"status": "error", "message": str(e)}), 500


@audit_bp.route("/eve/inquiry/<int:inquiry_id>/escalate", methods=["POST"])
@login_required
def escalate_eve_inquiry(inquiry_id):
    """Escalate inquiry to finding."""
    try:
        from app.models.eve_models import EveInquiry, EveAssuranceState
        from datetime import datetime

        inquiry = EveInquiry.query.get(inquiry_id)
        if not inquiry:
            return jsonify({"status": "error", "message": "Inquiry not found"}), 404

        if inquiry.status == "ESCALATED_TO_FINDING":
            return jsonify({"status": "error", "message": "Inquiry already escalated"}), 400

        data = request.get_json() or {}
        escalation_reason = data.get("escalation_reason", "").strip()
        if not escalation_reason:
            return jsonify({"status": "error", "message": "Escalation reason is required"}), 400

        inquiry.status = "ESCALATED_TO_FINDING"
        inquiry.escalation_reason = escalation_reason
        inquiry.resolved_at = datetime.utcnow()
        inquiry.resolved_by = current_user.id

        assurance = EveAssuranceState.query.filter_by(
            project_checklist_id=inquiry.project_checklist_id
        ).first()
        if assurance:
            assurance.escalated_inquiry_count = (assurance.escalated_inquiry_count or 0) + 1
            assurance.assurance_score = max(0.0, (assurance.assurance_score or 0.0) - 0.1)
            assurance.last_updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Inquiry escalated to finding",
            "inquiry_id": inquiry_id,
            "new_status": inquiry.status,
        })

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error escalating inquiry {inquiry_id}")
        return jsonify({"status": "error", "message": str(e)}), 500


@audit_bp.route("/eve/assurance/<int:project_checklist_id>", methods=["GET"])
@login_required
def get_eve_assurance_state(project_checklist_id):
    """Fetch assurance state for a project checklist."""
    try:
        from app.models.eve_models import EveAssuranceState

        state = EveAssuranceState.query.filter_by(
            project_checklist_id=project_checklist_id
        ).first()

        if not state:
            return jsonify({
                "status": "success",
                "project_checklist_id": project_checklist_id,
                "assurance_state": None,
                "message": "No assurance state found — run Step 5 first"
            })

        return jsonify({
            "status": "success",
            "project_checklist_id": project_checklist_id,
            "assurance_state": {
                "assurance_score": round(state.assurance_score or 0.0, 2),
                "coverage_score": round(state.coverage_score or 0.0, 2),
                "evidence_quality_score": round(state.evidence_quality_score or 0.0, 2),
                "oe_reliability_score": round(state.oe_reliability_score or 0.0, 2),
                "total_checklist_items": state.total_checklist_items,
                "evaluated_items": state.evaluated_items,
                "passed_items": state.passed_items,
                "failed_items": state.failed_items,
                "partial_items": state.partial_items,
                "needs_review_items": state.needs_review_items,
                "inquiry_count": state.inquiry_count,
                "contradiction_count": state.contradiction_count,
                "resolved_inquiry_count": state.resolved_inquiry_count,
                "escalated_inquiry_count": state.escalated_inquiry_count,
                "total_evidence_count": state.total_evidence_count,
                "admissible_evidence_count": state.admissible_evidence_count,
                "last_updated_at": state.last_updated_at.isoformat() if state.last_updated_at else None,
            }
        })

    except Exception as e:
        logger.exception(f"Error fetching assurance state for checklist {project_checklist_id}")
        return jsonify({"status": "error", "message": str(e)}), 500
