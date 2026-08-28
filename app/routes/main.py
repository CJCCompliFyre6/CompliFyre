from flask import (
    Blueprint,
    render_template,
    request,
    flash,
    jsonify,
    redirect,
    url_for,
    current_app,
    session,
    Response,
)
from app.models.user import *
from app.models.ai import *
from werkzeug.security import generate_password_hash, check_password_hash
from app.utils.input_security import validate_upload_file
from app import db, mail
from sqlalchemy.exc import IntegrityError
from app.services.automate_task import *
from app.services.manual_task import *
from celery.result import AsyncResult
from flask_login import login_required, current_user, login_user, logout_user
from app.models.task_status import TaskStatus  # Import the global instance

import uuid
import json
import pyotp
import qrcode
import io, random
import base64
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Message
from app.utils.bread_crumb import add_to_breadcrumb
from app.utils.permission_handler import role_required
from werkzeug.utils import secure_filename
import pandas as pd
import redis
from config import settings


ALLOWED_EXTENSIONS = {"xlsx", "xls", "csv"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


main_bp = Blueprint("main", __name__)  # Create a blueprint


@main_bp.before_request
def check_single_session():
    if current_user.is_authenticated:
        token_in_db = current_user.session_token
        token_in_session = session.get("session_token")

        if token_in_session is None or token_in_session != token_in_db:
            logout_user()
            flash(
                "You have been logged out because your account was accessed from another device.",
                "warning",
            )
            if (
                request.endpoint
                and "static" not in request.endpoint
                and request.endpoint != "main.login"
            ):
                return redirect(url_for("main.login"))


# ++++++++++++++++++++++++++++++++++++++++++++


@main_bp.route("/")
def home():
    return render_template("/dashboards/re/complifyre_main.html")


@main_bp.route("/complifyre")
@role_required("COMPLIFYRE")
def comp_dash():
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
            all_guidelines = Guidelines.query.all()
            print(all_proj)
            info_data = {
                "total_clients": len(clients),
                "total_projects": len(all_proj),
                "total_guidelines": len(all_guidelines),
            }
        return render_template(
            "/dashboards/auditor/audit_dash.html",
            organization=organization,
            info_data=info_data,
        )
    except Exception as err:
        current_app.logger.error(f"Unexpected error: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@main_bp.route("/login")
def login():
    return render_template("/dashboards/re/login.html")


# +++ ADDED LOGIN AND LOGOUT ROUTES +++
@main_bp.route("/login_user_route", methods=["POST"])
@limiter.limit("5 per minute")  # S-71: prevent ACS flood + brute force
def login_user_route():
    email = request.form.get("email")
    password = request.form.get("password")

    print(f"=== LOGIN ATTEMPT ===")
    print(f"Email: {email}")
    print(f"Password provided: {password}")

    # Normalize email
    normalized_email = email.strip().lower() if email else ""
    print(f"Normalized email: {normalized_email}")

    # === STEP 1: Try regular Users table (BOTH regular users AND contact persons are here now) ===
    user = Users.query.filter(
        db.func.lower(Users.email) == normalized_email,
        Users.status == "active"  # Only active users
    ).first()

    if user:
        print(f"Found User: {user.email}, Role ID: {user.role_id}")
        password_match = user.check_password(password)
        print(f"User password match: {password_match}")

        if password_match:
            print("User login successful!")

            if not user.email_verified:
                flash("Please verify your email address before logging in.", "warning")
                return redirect(url_for("main.login"))

            # === CHECK TFA ENABLED ===
            if user.tfa_enabled:
                print(f"TFA enabled for user: {user.email}")
                session["user_id_for_tfa"] = user.id
                verify_user_login(user)
                return redirect(url_for("main.verify_tfa_login"))

            # Generate new session token
            new_token = str(uuid.uuid4())
            user.session_token = new_token
            db.session.commit()

            # Login user
            login_user(user, remember=True)
            session["session_token"] = new_token

            # Check user role and redirect accordingly
            if user.role_id == 1:  # Auditor role (including contact persons)
                print(f"User is an auditor (role_id: {user.role_id})")
                
                # Check if this user is also an OrganizationContact
                org_contact = OrganizationContacts.query.filter_by(email=user.email).first()
                if org_contact:
                    print(f"User is also an OrganizationContact: {org_contact.name}")
                    session["user_type"] = "auditor"  # Treat as regular auditor
                    session["organization_id"] = org_contact.organization_id
                    session["contact_id"] = org_contact.contact_id
                    print(f"Set session for OrganizationContact: org_id={org_contact.organization_id}, contact_id={org_contact.contact_id}")
                else:
                    session["user_type"] = "auditor"  # Regular auditor
                    print("User is a regular auditor")
                
                # Redirect ALL auditors (including contact persons) to audit dashboard
                return redirect(url_for("audit.dashboard"))
                
            elif user.role_id == 2:  # Admin role (adjust based on your role IDs)
                session["user_type"] = "admin"
                return redirect(url_for("admin.dashboard"))
                
            elif user.role_id == 9:  # COMPLIFYRE role
                session["user_type"] = "complifyre"
                return redirect(url_for("re.guidelines"))

            elif user.role_id == 10:  # RE role
                session["user_type"] = "re"
                return redirect(url_for("re.guidelines"))

            else:
                session["user_type"] = "regular_user"
                return redirect(url_for("main.home"))
                
        else:
            print("User password mismatch")

    # === STEP 2: Legacy check for OrganizationContacts (for backward compatibility) ===
    # This can be removed once all contacts are migrated to Users table
    org_contact = OrganizationContacts.query.filter(
        db.func.lower(OrganizationContacts.email) == normalized_email
    ).first()

    if org_contact:
        print(f"Found Legacy OrganizationContact: {org_contact.name}")
        password_match = org_contact.check_password(password)
        print(f"Legacy OrganizationContact password match: {password_match}")

        if password_match:
            print("Legacy OrganizationContact login successful!")
            
            # Check if this contact already has a Users record
            existing_user = Users.query.filter_by(email=org_contact.email).first()
            if not existing_user:
                # Migrate this contact to Users table
                print("🔄 Migrating legacy OrganizationContact to Users table...")
                try:
                    user = Users()
                    user.email = org_contact.email
                    user.name = org_contact.name
                    user.phone_no = org_contact.phone
                    user.role_id = 1  # Auditor role
                    user.auditor_profile_id = org_contact.organization_id
                    user.email_verified = True
                    user.status = "active"
                    user.tfa_enabled = True  # TFA enabled by default for migrated users
                    user.set_password(password)  # Use the same password
                    user.session_token = str(uuid.uuid4())
                    
                    db.session.add(user)
                    db.session.commit()
                    print(f"✅ Migrated {org_contact.email} to Users table")
                    
                    # Login the newly created user
                    login_user(user, remember=True)
                    session["session_token"] = user.session_token
                    session["user_type"] = "auditor"
                    session["organization_id"] = org_contact.organization_id
                    session["contact_id"] = org_contact.contact_id
                    
                    return redirect(url_for("audit.dashboard"))
                    
                except Exception as migration_error:
                    print(f"❌ Migration failed: {str(migration_error)}")
                    # Fall back to old OrganizationContact login
                    pass
            
            # If migration failed or user already exists, use OrganizationContact login
            # OrganizationContacts don't have TFA, so proceed directly
            new_token = str(uuid.uuid4())
            org_contact.session_token = new_token
            db.session.commit()

            login_user(org_contact, remember=True)
            session["user_type"] = "auditor"  # Treat as auditor
            session["organization_id"] = org_contact.organization_id
            session["contact_id"] = org_contact.contact_id
            session["session_token"] = new_token

            print(f"Legacy OrganizationContact logged in: {org_contact.name}")
            return redirect(url_for("audit.dashboard"))
        else:
            print("Legacy OrganizationContact password mismatch")

    # === STEP 3: If neither user type matches ===
    print("=== LOGIN FAILED ===")
    flash("Invalid email or password.", "error")
    return redirect(url_for("main.login"))



@main_bp.route("/logout")
@login_required
def logout():
    if current_user.is_authenticated:
        current_user.session_token = None
        db.session.commit()
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.login"))


# ++++++++++++++++++++++++++++++++++++++++


# +++ HELPER FUNCTIONS FOR EMAIL +++
def send_verification_email(user_email):
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    token = serializer.dumps(user_email, salt="email-verification-salt")
    verify_url = url_for("main.verify_email", token=token, _external=True)
    msg = Message(
        subject="Complifyre - Verify Your Email Address",
        recipients=[user_email],
        html=f"<p>Welcome! Click the link to verify your email:</p><p><a href='{verify_url}'>Verify Email</a></p>",
    )
    mail.send(msg)


def verify_user_login(user):
    """
    Generate a 6-digit OTP, store it in the database (or session),
    and send it via email.

    Fix 2026-08-09: switched the actual send from Flask-Mail's
    mail.send() (crackerjacktech.com relay, permanent MailChannels
    [ESA] abuse block found the previous night) to Azure Communication
    Services via the shared send_via_azure_email() helper. OTP
    generation and storage logic is unchanged.
    """
    from app.utils.email_service import send_via_azure_email

    # Generate a 6-digit OTP
    otp = str(random.randint(100000, 999999))

    # Store OTP in user record (or Redis/cache for expiry handling)
    user.tfa_secret = str(otp)
    db.session.commit()

    # Send OTP email
    send_via_azure_email(
        recipient_email=user.email,
        subject="Complifyre - Your Login OTP",
        html_body=f"<p>Welcome back!</p><p>Your OTP code is: <b>{otp}</b></p>",
    )


def send_password_reset_email(user_email):
    """
    Fix 2026-08-09: switched the actual send from Flask-Mail's
    mail.send() (crackerjacktech.com relay, permanent MailChannels
    [ESA] abuse block found the previous night) to Azure Communication
    Services via the shared send_via_azure_email() helper. Token
    generation logic is unchanged.
    """
    from app.utils.email_service import send_via_azure_email

    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    token = serializer.dumps(user_email, salt="password-reset-salt")
    reset_url = url_for("main.reset_password_token", token=token, _external=True)
    send_via_azure_email(
        recipient_email=user_email,
        subject="Complifyre - Password Reset Request",
        html_body=f"<p>Click the link to reset your password:</p><p><a href='{reset_url}'>Reset Password</a></p>",
    )


def validate_password_complexity(password):
    """
    Validate password complexity requirements
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one number"
    
    if not re.search(r'[!@#$%^&*]', password):
        return False, "Password must contain at least one special character (!@#$%^&*)"
    
    return True, "Password meets complexity requirements"

@main_bp.route("/register_user", methods=["GET"])
def register_user():
    roles = Roles.query.all()
    return render_template("/dashboards/re/register.html", roles=roles)


# --- MODIFIED create_user ROUTE ---
@main_bp.route("/create_user", methods=["POST"])
def create_user():
    try:
        # (Your existing validation code remains here...)
        role_id = request.form.get("role")
        email = request.form.get("email")
        phone_no = request.form.get("phone_no")
        fname = request.form.get("fname")
        lname = request.form.get("lname")
        password = request.form.get("password_hash")
        confirm_password = request.form.get("confirm_password")

        # Basic validation
        if not all([role_id, email, phone_no, fname, lname, password, confirm_password]):
            flash("All fields are required.", "error")
            return redirect(url_for("main.register_user"))


        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for("main.register_user"))

         # Password complexity validation
        is_valid_password, password_message = validate_password_complexity(password)
        if not is_valid_password:
            flash(f"Password complexity error: {password_message}", "error")
            return redirect(url_for("main.register_user"))    

        existing_user = Users.query.filter_by(email=email).first()
        if existing_user:
            flash(f'User with email "{email}" already exists.')
            return redirect(url_for("main.register_user"))

        full_name = f"{str(request.form.get('fname')).capitalize()} {str(request.form.get('lname')).capitalize()}"
        password_hash = generate_password_hash(password)

        user_add = Users(
            email=email,
            name=full_name,
            phone_no=request.form.get("phone_no"),
            password_hash=password_hash,
            role_id=role_id,
        )

        db.session.add(user_add)
        db.session.commit()

        # Send the verification email
        try:
            send_verification_email(user_add.email)
            flash(
                "User Created! Please check your email to verify your account.",
                "success",
            )
        except Exception as e:
            current_app.logger.error(f"Email sending failed: {e}")
            flash(
                "User created, but could not send verification email. Please contact support.",
                "warning",
            )

        return redirect(url_for("main.login"))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"User creation failed: {e}")
        flash("An unexpected error occurred. Please try again.", "error")
        return redirect(url_for("main.register_user"))


# +++ NEW ROUTES FOR AUTH FEATURES +++


# 1. Email Verification
@main_bp.route("/verify-email/<token>")
def verify_email(token):
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    try:
        email = serializer.loads(
            token, salt="email-verification-salt", max_age=3600
        )  # 1 hour
    except Exception:
        flash("The verification link is invalid or has expired.", "error")
        return redirect(url_for("main.login"))

    user = Users.query.filter_by(email=email).first_or_404()
    if user.email_verified:
        flash("Account already verified. Please log in.", "info")
    else:
        user.email_verified = True
        user.tfa_enabled = True
        db.session.commit()
        flash("Email verified! You can now log in.", "success")
    return redirect(url_for("main.login"))


# 2. Password Reset
@main_bp.route("/request-reset", methods=["GET", "POST"])
def request_password_reset():
    if request.method == "POST":
        email = request.form.get("email")
        user = Users.query.filter_by(email=email).first()
        if user:
            send_password_reset_email(user.email)
        flash(
            "If an account exists for that email, a reset link has been sent.", "info"
        )
        return redirect(url_for("main.login"))
    return render_template("dashboards/re/request_reset.html")


@main_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password_token(token):
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    try:
        email = serializer.loads(
            token, salt="password-reset-salt", max_age=1800
        )  # 30 mins
    except Exception:
        flash("The password reset link is invalid or has expired.", "error")
        return redirect(url_for("main.request_password_reset"))

    user = Users.query.filter_by(email=email).first_or_404()
    if request.method == "POST":
        password = request.form.get("password")
        user.password_hash = generate_password_hash(password)
        db.session.commit()
        flash("Password updated! You can now log in.", "success")
        return redirect(url_for("main.login"))
    return render_template("dashboards/re/reset_password.html", token=token)


# 3. Two-Factor Authentication
@main_bp.route("/setup-tfa")
@login_required
def setup_tfa():
    if current_user.tfa_enabled:
        flash("TFA is already enabled.", "info")
        return redirect(url_for("main.my_profile"))

    secret = pyotp.random_base32()
    current_user.tfa_secret = secret
    db.session.commit()

    provisioning_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.email, issuer_name="Complifyre"
    )
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")

    return render_template(
        "dashboards/re/setup_tfa.html", qr_code=img_str, secret=secret
    )


@main_bp.route("/verify-tfa-setup", methods=["POST"])
@login_required
def verify_tfa_setup():
    token = request.form.get("token")
    if pyotp.TOTP(current_user.tfa_secret).verify(token):
        current_user.tfa_enabled = True
        db.session.commit()
        flash("TFA enabled successfully!", "success")
        return redirect(url_for("main.my_profile"))
    else:
        flash("Invalid code. Please try again.", "error")
        return redirect(url_for("main.setup_tfa"))


@main_bp.route("/verify-tfa-login", methods=["GET", "POST"])
@limiter.limit("5 per minute")  # S-71: prevent OTP brute force
def verify_tfa_login():
    if "user_id_for_tfa" not in session:
        return redirect(url_for("main.login"))

    user = Users.query.get(session["user_id_for_tfa"])

    if request.method == "POST":
        token = request.form.get("token")

        # ✅ Check against OTP stored in DB
        if str(token) == user.tfa_secret:
            session.pop("user_id_for_tfa", None)
            user.email_otp = None  # clear OTP after successful login
            # Handle single session
            new_token = str(uuid.uuid4())
            user.session_token = new_token
            db.session.commit()
            login_user(user)
            session["session_token"] = new_token
            # Defensive guard added 2026-07-31: role_id was found missing
            # on some self-signup users, causing a 500 here. Root cause
            # fixed in loi/view.py activation_submit; this guard just
            # prevents a repeat 500 if a role is ever missing again.
            if current_user.role and current_user.role.name == "COMPLIFYRE":
                return redirect(url_for("main.comp_dash"))
            elif current_user.role and current_user.role.name == "AUDITOR":
                return redirect(url_for("audit.dashboard"))
            return redirect(url_for("main.home"))
        else:
            flash("Invalid OTP code.", "error")

    return render_template("dashboards/re/verify_tfa_login.html")


@main_bp.route("/upload-and-process", methods=["POST"])
@login_required
def upload_file_and_start_processing():
    """
    Receives a file and schedules the processing task.
    """
    # Check if a file was uploaded in the request
    if "file" not in request.files:
        return (
            jsonify({"status": "error", "message": "No file part in the request"}),
            400,
        )

    file = request.files["file"]

    print(file)
    filename = file.filename
    file_content = file.read()
    # print(file_content)

    # If the user does not select a file, the browser submits an empty part without a filename
    if filename == "":
        return jsonify({"status": "error", "message": "No selected file"}), 400

    _sec = validate_upload_file(filename, context="guideline")
    if not _sec["ok"]:
        return jsonify({"status": "error", "message": _sec["error"]}), 400

    if file:
        # Pass the file directly to the Celery task.
        # Celery will handle the serialization and deserialization.
        task = process_all_activities.delay(filename, file_content)
        return (
            jsonify(
                {
                    "status": "success",
                    "message": "File processing started.",
                    "task_id": task.id,
                }
            ),
            202,
        )

    return jsonify({"status": "error", "message": "An unexpected error occurred"}), 500


##Manual Extraction of Guidelines, Clauses, activities and testprocedure.


def _json_response(status: str, message: str, code: int = 200, **extra):
    payload = {"status": status, "message": message}
    if extra:
        payload.update(extra)
    return jsonify(payload), code


@main_bp.route("/guideline-extraction-progress/<task_id>")
def guideline_extraction_progress(task_id):
    """Server-Sent Events endpoint for guideline extraction progress updates"""

    def generate():
        redis_conn = get_redis_connection()
        last_progress = None

        try:
            while True:
                progress_data = redis_conn.get(f"guideline_progress:{task_id}")

                if progress_data:
                    progress_data = json.loads(progress_data)

                    # Only send if progress has changed
                    if progress_data != last_progress:
                        yield f"data: {json.dumps(progress_data)}\n\n"
                        last_progress = progress_data

                        # Stop if task is completed or failed
                        if progress_data["status"] in ["COMPLETED", "FAILED", "ERROR"]:
                            logger.info(
                                f"Guideline extraction task {task_id} completed, closing SSE connection"
                            )
                            break

                time.sleep(2)  # Check every 2 seconds

        except GeneratorExit:
            logger.info(
                f"SSE connection closed for task {task_id} (client disconnected)"
            )
        except Exception as e:
            logger.error(f"Error in guideline SSE stream for task {task_id}: {e}")
            yield f"data: {json.dumps({'status': 'ERROR', 'progress': 0, 'message': str(e)})}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "X-Accel-Buffering": "no",
        },
    )


@main_bp.route("/upload-guidelines", methods=["POST"])
@login_required
def upload_file_and_extract_guidelines():
    """
    Receives a file and schedules guideline extraction.
    """
    try:
        if "file" not in request.files:
            return _json_response("error", "No file part in the request", 400)

        file = request.files["file"]
        if not file or file.filename.strip() == "":
            return _json_response("error", "No selected file", 400)

        filename = file.filename
        file_content = file.read()
        if not file_content:
            return _json_response("error", "Uploaded file is empty", 400)

        _sec = validate_upload_file(filename, context="guideline")
        if not _sec["ok"]:
            return _json_response("error", _sec["error"], 400)

        # Get the current user's ID
        user_id = current_user.id

        # Start the celery task with user_id
        task = extract_guidelines.delay(filename, file_content, user_id)

        # Store initial task status
        # Import here to avoid circular imports
        task_status = TaskStatus()
        task_status.set_status(
            task_id=task.id,
            user_id=user_id,
            task_name="extract_guidelines",
            status="pending",
            progress=0,
            message="Task queued",
        )
        return _json_response(
            "success", "Guideline extraction started.", 202, task_id=task.id
        )

    except Exception as e:
        return _json_response("error", f"Unexpected server error: {str(e)}", 500)





from flask import redirect, request, flash, url_for


@main_bp.route("/clause-extraction-progress/<int:guideline_id>")
def clause_extraction_progress(guideline_id):
    """SSE endpoint for real-time clause extraction progress"""

    def generate():
        redis_conn = get_redis_connection()
        last_data = None
        heartbeat_counter = 0

        while True:
            # Get current progress from Redis
            progress_data = redis_conn.get(f"clause_progress:{guideline_id}")

            if progress_data:
                data = json.loads(progress_data)
                # Only send if data has changed
                if data != last_data:
                    yield f"data: {json.dumps(data)}\n\n"
                    last_data = data

                    # Stop if completed or failed
                    if data.get("status") in ["COMPLETED", "FAILED"]:
                        break
            
            # Heartbeat every 30 seconds to keep connection alive
            heartbeat_counter += 1
            if heartbeat_counter >= 30:
                yield f": heartbeat\n\n"
                heartbeat_counter = 0

            time.sleep(1)  # Check every second

    return Response(generate(), mimetype="text/event-stream")


def get_redis_connection():
    """Get Redis connection for progress tracking"""

    return redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        db=settings.CELERY_REDIS_DB,
        decode_responses=True,
    )


@main_bp.route("/extract-clauses/<int:guideline_id>", methods=["GET"])
def extract_clauses_route(guideline_id):
    """
    Trigger clause extraction. If structure map confirmed — start directly.
    If not — redirect to structure map verification screen first.
    """
    try:
        if not guideline_id:
            flash("Invalid guideline ID", "error")
            return redirect(request.referrer)

        guideline = Guidelines.query.get(guideline_id)
        if not guideline:
            flash("Guideline not found", "error")
            return redirect(request.referrer)

        existing_map = guideline.structure_map
        if existing_map and existing_map.get("confirmed"):
            existing_clauses = Clauses.query.filter_by(guideline_id=guideline_id).first()
            if existing_clauses:
                flash("Clauses already exist. Running extraction will add new clauses only.", "warning")
            task = extract_clauses.delay(guideline_id)
            flash("Clause extraction started. Refresh page after a few minutes.", "success")
            return redirect(request.referrer)
        else:
            return redirect(url_for("main.structure_map_review", guideline_id=guideline_id))

    except Exception as e:
        flash(f"Unexpected server error: {str(e)}", "error")
        return redirect(request.referrer)


@main_bp.route("/structure-map/<int:guideline_id>", methods=["GET"])
def structure_map_review(guideline_id):
    """Show structure map verification screen."""
    try:
        guideline = Guidelines.query.get(guideline_id)
        if not guideline:
            flash("Guideline not found", "error")
            return redirect(request.referrer or "/")

        guideline_data = guideline.guideline_data or {}
        guideline_name = guideline_data.get("DocumentDetails", {}).get("DocumentName", "Unknown Guideline")
        regulator_name = guideline_data.get("Regulator", "Unknown")

        existing_map = guideline.structure_map
        if not existing_map:
            from app.services.manual_task import generate_structure_map
            file_record = guideline.file
            if not file_record:
                flash("No file found for this guideline", "error")
                return redirect(request.referrer or "/")
            structure_map = generate_structure_map(file_record.path, guideline_id, regulator_name)
        else:
            structure_map = existing_map

        return render_template(
            "structure_map_review.html",
            guideline_id=guideline_id,
            guideline_name=guideline_name,
            structure_map=structure_map,
        )
    except Exception as e:
        logger.error(f"Error in structure_map_review: {e}")
        flash(f"Error generating structure map: {str(e)}", "error")
        return redirect(request.referrer or "/")


@main_bp.route("/clear-structure-map/<int:guideline_id>", methods=["POST"])
def clear_structure_map(guideline_id):
    """Clear structure map so it regenerates fresh via LLM on next review page load."""
    try:
        guideline = Guidelines.query.get(guideline_id)
        if not guideline:
            return jsonify({"status": "error", "message": "Guideline not found"}), 404
        guideline.structure_map = None
        db.session.commit()
        return jsonify({"status": "success", "message": "Structure map cleared. Reload to regenerate."}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error clearing structure map: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
@main_bp.route("/confirm-structure-map/<int:guideline_id>", methods=["POST"])
def confirm_structure_map(guideline_id):
    """Save confirmed structure map and trigger extraction."""
    try:
        guideline = Guidelines.query.get(guideline_id)
        if not guideline:
            return jsonify({"status": "error", "message": "Guideline not found"}), 404

        data = request.get_json()
        if not data or "sections" not in data:
            return jsonify({"status": "error", "message": "Invalid structure map data"}), 400

        confirmed_map = data
        confirmed_map["confirmed"] = True
        guideline.structure_map = confirmed_map
        db.session.commit()

        # Delete existing clauses if any
        existing_clauses = Clauses.query.filter_by(guideline_id=guideline_id).all()
        if existing_clauses:
            for clause in existing_clauses:
                ComplianceActivities.query.filter_by(clause_id=clause.id).delete()
                db.session.delete(clause)
            db.session.commit()

        task = extract_clauses.delay(guideline_id)
        return jsonify({
            "status": "success",
            "message": "Structure map confirmed. Extraction started.",
            "task_id": task.id,
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error confirming structure map: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@main_bp.route("/test-raw-model")
def test_raw_model():
    """Test if RawLLMResponse model can save data"""
    try:
        from app import db
        from app.models import RawLLMResponse

        test_obj = RawLLMResponse(
            guideline_id=96,
            task_type="test",
            page_range="test pages 1-2",
            raw_response="Test raw response data",
        )
        db.session.add(test_obj)
        db.session.commit()
        return f"✅ RawLLMResponse test successful! Saved with ID: {test_obj.id}"
    except Exception as e:
        return f"❌ RawLLMResponse test failed: {str(e)}"


@main_bp.route("/regenerate-clauses/<int:guideline_id>", methods=["POST"])
def regenerate_clauses_route(guideline_id):
    """
    Delete existing clauses and regenerate new ones
    """
    try:
        if not guideline_id:
            return jsonify({"status": "error", "message": "Invalid guideline ID"}), 400

        # Update progress - starting deletion
        update_progress(
            guideline_id, "PROCESSING", 10, "Starting deletion of existing clauses..."
        )

        # Delete existing clauses and their related records
        existing_clauses = Clauses.query.filter_by(guideline_id=guideline_id).all()
        clauses_deleted = 0

        for clause in existing_clauses:
            # Delete related compliance activities first
            ComplianceActivities.query.filter_by(clause_id=clause.id).delete()
            db.session.delete(clause)
            clauses_deleted += 1

        db.session.commit()

        # Update progress - deletion completed
        update_progress(
            guideline_id,
            "PROCESSING",
            25,
            f"Deleted {clauses_deleted} existing clauses. Starting regeneration...",
        )

        task = extract_clauses.delay(guideline_id)
        return (
            jsonify(
                {
                    "status": "success",
                    "message": "Clause regeneration started successfully",
                    "clauses_deleted": clauses_deleted,
                    "task_id": task.id,
                }
            ),
            200,
        )

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in regenerate_clauses_route: {str(e)}")
        update_progress(guideline_id, "ERROR", 100, f"Regeneration failed: {str(e)}")
        return (
            jsonify(
                {"status": "error", "message": f"Unexpected server error: {str(e)}"}
            ),
            500,
        )


@main_bp.route("/extract-activities/<int:clause_id>", methods=["POST"])
def extract_activities_route(clause_id):
    """
    Trigger activity extraction for a given clause.
    """
    try:
        if not clause_id:
            return _json_response("error", "Invalid clause ID", 400)

        task = extract_activities.delay(clause_id)
        return _json_response(
            "success", "Activity extraction started.", 202, task_id=task.id
        )

    except Exception as e:
        return _json_response("error", f"Unexpected server error: {str(e)}", 500)


@main_bp.route("/extract-test-procedures/<int:activity_id>", methods=["POST"])
def extract_test_procedures_route(activity_id):
    """
    Trigger test procedure extraction for a given activity.
    """
    try:
        if not activity_id:
            return _json_response("error", "Invalid activity ID", 400)

        task = extract_test_procedures.delay(activity_id)
        return _json_response(
            "success", "Test procedure extraction started.", 202, task_id=task.id
        )

    except Exception as e:
        return _json_response("error", f"Unexpected server error: {str(e)}", 500)


@main_bp.route("/compliance-extraction-progress/<task_id>")
def compliance_extraction_progress(task_id):
    """
    Server-Sent Events endpoint for compliance extraction progress
    """

    def generate():
        import time

        # Use the helper to get a Redis connection
        redis_conn = get_redis_connection()
        last_progress = None

        while True:
            # Get progress from Redis or database
            progress_data = redis_conn.get(f"compliance_progress:{task_id}")

            if progress_data:
                # Try to parse JSON, if it's already a dict keep as is
                try:
                    progress_data = json.loads(progress_data)
                except Exception:
                    pass

                # Only send if progress changed
                if progress_data != last_progress:
                    yield f"data: {json.dumps(progress_data)}\n\n"
                    last_progress = progress_data

                    # Stop if task is completed or failed
                    if progress_data.get("status") in ["COMPLETED", "FAILED", "ERROR"]:
                        break

            time.sleep(1)  # Check every second

    return Response(generate(), mimetype="text/event-stream")


@main_bp.route("/extract-all/<int:guideline_id>", methods=["POST"])
def extract_all_route(guideline_id):
    """
    Trigger activities and test procedure extraction for all clauses of a guideline.
    Prevents duplicate triggers - only one task per guideline at a time.
    """
    try:
        if not guideline_id:
            return jsonify({"status": "error", "message": "Invalid guideline ID"}), 400

        guideline = Guidelines.query.get(guideline_id)
        if not guideline:
            return jsonify({"status": "error", "message": "Guideline not found"}), 404
        if not guideline.clause_review_completed_at:
            return jsonify({
                "status": "error",
                "message": "Clause classification review must be marked complete before generating activities. Visit the Clause Review page first.",
            }), 403

        # Check if a task is already running for this guideline
        redis_conn = get_redis_connection()
        active_task_key = f"active_extraction:{guideline_id}"
        existing_task_id = redis_conn.get(active_task_key)

        if existing_task_id:
            if isinstance(existing_task_id, bytes):
                existing_task_id = existing_task_id.decode("utf-8")
            # Check if task is still running
            from celery.result import AsyncResult
            task_result = AsyncResult(existing_task_id)
            if task_result.state in ["PENDING", "STARTED", "RETRY"]:
                return (
                    jsonify(
                        {
                            "status": "already_running",
                            "message": "Extraction already in progress for this guideline",
                            "task_id": existing_task_id,
                            "guideline_id": guideline_id,
                        }
                    ),
                    200,
                )

        # Auto-cleanup duplicates before starting
        from app.models.ai import ComplianceActivities, Clauses
        from sqlalchemy import text
        clause_ids = [r[0] for r in db.session.execute(
            text("SELECT id FROM clauses WHERE guideline_id = :gid"),
            {"gid": guideline_id}
        ).fetchall()]

        if clause_ids:
            clause_ids_str = ",".join(map(str, clause_ids))
            # Find clauses with too many activities (>10 = duplicates)
            dupes = db.session.execute(text(f"""
                SELECT clause_id, COUNT(*) as cnt
                FROM compliance_activities
                WHERE clause_id IN ({clause_ids_str})
                GROUP BY clause_id
                HAVING COUNT(*) > 10
            """)).fetchall()

            if dupes:
                logger.warning(f"Found {len(dupes)} clauses with duplicate activities for guideline {guideline_id}. Auto-cleaning...")
                for clause_id, cnt in dupes:
                    # Keep first 8, delete rest (with all child records)
                    keep_ids = [r[0] for r in db.session.execute(text(f"""
                        SELECT id FROM compliance_activities
                        WHERE clause_id = {clause_id} ORDER BY id LIMIT 8
                    """)).fetchall()]
                    if keep_ids:
                        keep_str = ",".join(map(str, keep_ids))
                        del_acts = [r[0] for r in db.session.execute(text(f"""
                            SELECT id FROM compliance_activities
                            WHERE clause_id = {clause_id} AND id NOT IN ({keep_str})
                        """)).fetchall()]
                        if del_acts:
                            del_str = ",".join(map(str, del_acts))
                            ctrl_ids = [r[0] for r in db.session.execute(text(f"SELECT id FROM control_activities WHERE compliance_activity_id IN ({del_str})")).fetchall()]
                            if ctrl_ids:
                                ctrl_str = ",".join(map(str, ctrl_ids))
                                ts_ids = [r[0] for r in db.session.execute(text(f"SELECT id FROM test_steps WHERE control_id IN ({ctrl_str})")).fetchall()]
                                if ts_ids:
                                    ts_str = ",".join(map(str, ts_ids))
                                    db.session.execute(text(f"DELETE FROM document_reviews WHERE test_procedure_id IN ({ts_str})"))
                                    db.session.execute(text(f"DELETE FROM interview_roles WHERE interview_id IN (SELECT id FROM interviews WHERE test_procedure_id IN ({ts_str}))"))
                                    db.session.execute(text(f"DELETE FROM interview_questions WHERE interview_id IN (SELECT id FROM interviews WHERE test_procedure_id IN ({ts_str}))"))
                                    db.session.execute(text(f"DELETE FROM interviews WHERE test_procedure_id IN ({ts_str})"))
                                    db.session.execute(text(f"DELETE FROM test_steps WHERE id IN ({ts_str})"))
                                db.session.execute(text(f"DELETE FROM control_evidences WHERE control_id IN ({ctrl_str})"))
                                db.session.execute(text(f"DELETE FROM control_activities WHERE id IN ({ctrl_str})"))
                            db.session.execute(text(f"DELETE FROM compliance_activities WHERE id IN ({del_str})"))
                db.session.commit()
                logger.info(f"Auto-cleanup complete for guideline {guideline_id}")

        task = extract_selected_activities_and_tests.delay(guideline_id, clause_ids)

        # Store active task in Redis (expires in 4 hours)
        redis_conn.setex(active_task_key, 14400, task.id)

        return (
            jsonify(
                {
                    "status": "success",
                    "message": "Compliance activities extraction started successfully",
                    "task_id": task.id,
                    "guideline_id": guideline_id,
                }
            ),
            200,
        )

    except Exception as e:
        return (
            jsonify(
                {"status": "error", "message": f"Unexpected server error: {str(e)}"}
            ),
            500,
        )


@main_bp.route("/extract-selected", methods=["POST"])
def extract_selected_route():
    """
    Trigger activities and test procedure extraction for selected clauses only
    """
    try:
        data = request.get_json()
        guideline_id = data.get("guideline_id")
        clause_ids = data.get("clause_ids", [])

        if not guideline_id or not clause_ids:
            return (
                jsonify(
                    {"status": "error", "message": "Invalid guideline ID or clause IDs"}
                ),
                400,
            )

        guideline = Guidelines.query.get(guideline_id)
        if not guideline:
            return jsonify({"status": "error", "message": "Guideline not found"}), 404
        if not guideline.clause_review_completed_at:
            return jsonify({
                "status": "error",
                "message": "Clause classification review must be marked complete before generating activities. Visit the Clause Review page first.",
            }), 403
        task = extract_selected_activities_and_tests.delay(guideline_id, clause_ids)
        return (
            jsonify(
                {
                    "status": "success",
                    "message": "Compliance activities extraction started for selected clauses",
                    "task_id": task.id,
                    "guideline_id": guideline_id,
                }
            ),
            200,
        )

    except Exception as e:
        return (
            jsonify(
                {"status": "error", "message": f"Unexpected server error: {str(e)}"}
            ),
            500,
        )


# ==============================================================


@main_bp.route("/guideline/edit/<int:guideline_id>", methods=["GET"])
def show_infographic(guideline_id):
    """
    Render the infographic editor for a specific guideline with better error handling.
    """
    try:
        guideline_entry = Guidelines.query.get(guideline_id)
        if not guideline_entry:
            flash(f"Guideline with id {guideline_id} not found", "error")
            return redirect(url_for("main.dashboard"))

        # Ensure guideline_data is JSON-serializable for safe use in JS
        try:
            guideline_data = json.dumps(guideline_entry.guideline_data)
        except Exception as e:
            current_app.logger.error(
                f"Failed to serialize guideline_data for id {guideline_id}: {e}"
            )
            flash("Error loading guideline data.", "error")
            return redirect(url_for("main.dashboard"))

        return render_template(
            "dashboards/re/guideline_infographic.html",
            guideline_data=guideline_data,
            guideline_id=guideline_id,
        )

    except Exception as e:
        current_app.logger.error(f"Error fetching guideline {guideline_id}: {e}")
        flash("Unexpected error occurred while loading guideline.", "error")
        return redirect(request.referrer)


@main_bp.route("/api/guidelines/<int:guideline_id>", methods=["PUT"])
def update_guideline(guideline_id):
    """
    Update a guideline's JSON data via API.
    """
    try:
        guideline_entry = Guidelines.query.get(guideline_id)
        if not guideline_entry:
            return (
                jsonify({"error": f"Guideline with id {guideline_id} not found"}),
                404,
            )

        data = request.get_json()
        if not data or "guideline_data" not in data:
            return (
                jsonify({"error": "Invalid request. 'guideline_data' is required."}),
                400,
            )

        # Update the guideline data safely
        guideline_entry.guideline_data = data["guideline_data"]
        db.session.commit()

        return jsonify({"message": "Guideline updated successfully."}), 200

    except SQLAlchemyError as db_err:
        db.session.rollback()
        current_app.logger.error(
            f"Database error updating guideline {guideline_id}: {db_err}"
        )
        return jsonify({"error": "Database error while updating guideline."}), 500

    except Exception as e:
        current_app.logger.error(
            f"Unexpected error updating guideline {guideline_id}: {e}"
        )
        return (
            jsonify({"error": "Unexpected error occurred while updating guideline."}),
            500,
        )


@main_bp.route("/guidelines/<int:guideline_id>/delete", methods=["GET"])
def delete_guideline(guideline_id):
    """
    Delete a guideline and all its related entities using cascade.
    Redirects back to the referring page with a flash message.
    """
    guideline = Guidelines.query.get(guideline_id)
    if not guideline:
        flash(f"Guideline with ID {guideline_id} not found.", "error")
        return redirect(request.referrer or request.referrer or "/")

    try:
        db.session.delete(guideline)
        db.session.commit()
        flash(f"Guideline {guideline_id} deleted successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting guideline: {str(e)}", "error")

    return redirect(request.referrer or request.referrer or "/")


# ===========Clauses==================================================

UPLOAD_FOLDER = "uploads/clauses"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@main_bp.route("/guideline/<int:guideline_id>/clauses/add", methods=["GET", "POST"])
def add_clause(guideline_id):
    """
    Handles displaying the form to add a new clause for a specific guideline
    and processing the form submission.
    """
    # Fetch the guideline to ensure it exists
    guideline = Guidelines.query.get_or_404(guideline_id)
    if not guideline:
        flash("Guideline not found.", "danger")
        return redirect(request.referrer)  # Redirect to a home page or dashboard

    if request.method == "POST":
        clause_no = request.form.get("clause_no")
        clause_text = request.form.get("clause_text")

        if not clause_text:
            flash("Clause text is a required field.", "danger")
            return render_template(
                "dashboards/re/add_clause.html", guideline_id=guideline_id
            )

        # Create and save the new clause to the database
        new_clause = Clauses(
            clause_no=clause_no, clause_text=clause_text, guideline_id=guideline_id
        )
        db.session.add(new_clause)
        db.session.commit()

        flash("Clause added successfully!", "success")
        # Redirect to the guideline detail page or a list of clauses
        return redirect(request.referrer)

    return render_template("dashboards/re/add_clause.html", guideline_id=guideline_id)


@main_bp.route("/guideline/<int:guideline_id>/clauses/upload", methods=["POST"])
def upload_clauses(guideline_id):
    """
    Handles the bulk upload of clauses from an Excel or CSV file.
    """
    guideline = Guidelines.query.get_or_404(guideline_id)
    if not guideline:
        flash("Guideline not found.", "danger")
        return redirect(request.referrer)

    if "excel_file" not in request.files:
        flash("No file part", "danger")
        return redirect(request.url)

    file = request.files["excel_file"]

    if file.filename == "":
        flash("No selected file", "danger")
        return redirect(url_for("main.add_clause", guideline_id=guideline_id))

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        try:
            # Read the uploaded file using pandas
            df = (
                pd.read_excel(filepath)
                if filename.endswith((".xlsx", ".xls"))
                else pd.read_csv(filepath)
            )

            # Ensure required columns exist
            if "clause_text" not in df.columns:
                flash("File must contain a 'clause_text' column.", "danger")
                return redirect(url_for("main.add_clause", guideline_id=guideline_id))

            clauses_to_add = []
            for _, row in df.iterrows():
                # Create Clause objects for bulk insertion
                new_clause = Clauses(
                    clause_no=(
                        str(row["clause_no"])
                        if "clause_no" in row and pd.notna(row["clause_no"])
                        else None
                    ),
                    clause_text=row["clause_text"],
                    guideline_id=guideline_id,
                )
                clauses_to_add.append(new_clause)

            # Add all new clauses to the session and commit
            db.session.bulk_save_objects(clauses_to_add)
            db.session.commit()

            flash(f"{len(df)} clauses uploaded successfully!", "success")
        except Exception as e:
            flash(f"An error occurred while processing the file: {e}", "danger")
        finally:
            os.remove(filepath)  # Clean up the uploaded file

        return redirect(url_for("re.get_clause", guideline_id=guideline_id))
    else:
        flash("Invalid file type. Please upload an Excel or CSV file.", "danger")
        return redirect(url_for("main.add_clause", guideline_id=guideline_id))


@main_bp.route("/clauses/<int:clause_id>/edit", methods=["GET", "POST"])
def edit_clause(clause_id):
    """
    Handles displaying the form to edit an existing clause and
    processing the form submission.
    """
    clause = Clauses.query.get_or_404(clause_id)
    if not clause:
        flash("Clause not found.", "danger")
        return redirect(request.referrer)

    if request.method == "POST":
        # Update clause attributes from form data
        clause.clause_no = request.form.get("clause_no")
        clause.clause_text = request.form.get("clause_text")
        db.session.commit()

        flash("Clause updated successfully!", "success")
        return redirect(url_for("re.get_clause", guideline_id=clause.guideline_id))

    return render_template("dashboards/re/edit_clause.html", clause=clause)


@main_bp.route("/clauses/<int:clause_id>/delete", methods=["GET"])
def delete_clause(clause_id):
    """
    Complete deletion chain with corrected field names.
    """
    clause_to_delete = Clauses.query.get_or_404(clause_id)
    guideline_id = clause_to_delete.guideline_id

    try:
        current_app.logger.info(f"Starting deletion of clause {clause_id}")

        # Find compliance activities
        compliance_activities = ComplianceActivities.query.filter_by(
            clause_id=clause_id
        ).all()
        current_app.logger.info(
            f"Found {len(compliance_activities)} compliance activities"
        )

        for ca in compliance_activities:
            current_app.logger.info(f"Processing compliance activity {ca.id}")

            # Find control activities
            control_activities = ControlActivity.query.filter_by(
                compliance_activity_id=ca.id
            ).all()
            current_app.logger.info(
                f"Found {len(control_activities)} control activities"
            )

            for control_act in control_activities:
                current_app.logger.info(f"Processing control activity {control_act.id}")

                # FIRST: Delete entries from control_evidences many-to-many table
                control_evidences_count = db.session.execute(
                    db.delete(control_evidences).where(
                        control_evidences.c.control_id == control_act.id
                    )
                ).rowcount
                current_app.logger.info(
                    f"Deleted {control_evidences_count} entries from control_evidences table"
                )

                # Find test steps
                test_steps = TestSteps.query.filter_by(control_id=control_act.id).all()
                current_app.logger.info(f"Found {len(test_steps)} test steps")

                for ts in test_steps:
                    current_app.logger.info(f"Processing test step {ts.id}")

                    # Process interviews
                    interviews = Interview.query.filter_by(
                        test_procedure_id=ts.id
                    ).all()
                    current_app.logger.info(f"Found {len(interviews)} interviews")

                    for interview in interviews:
                        # FIRST: Delete project interview roles that reference original interview roles
                        project_roles_count = ProjectInterviewRole.query.filter(
                            ProjectInterviewRole.original_role_id.in_(
                                db.session.query(InterviewRole.id).filter(
                                    InterviewRole.interview_id == interview.id
                                )
                            )
                        ).delete(synchronize_session=False)
                        current_app.logger.info(
                            f"Deleted {project_roles_count} project interview roles"
                        )

                        # THEN: Delete original interview roles
                        roles_count = InterviewRole.query.filter_by(
                            interview_id=interview.id
                        ).delete()
                        current_app.logger.info(
                            f"Deleted {roles_count} interview roles"
                        )

                        # FIRST: Delete project interview questions that reference original questions
                        project_questions_count = ProjectInterviewQuestion.query.filter(
                            ProjectInterviewQuestion.original_question_id.in_(
                                db.session.query(InterviewQuestion.id).filter(
                                    InterviewQuestion.interview_id == interview.id
                                )
                            )
                        ).delete(synchronize_session=False)
                        current_app.logger.info(
                            f"Deleted {project_questions_count} project interview questions"
                        )

                        # THEN: Delete original interview questions
                        questions_count = InterviewQuestion.query.filter_by(
                            interview_id=interview.id
                        ).delete()
                        current_app.logger.info(
                            f"Deleted {questions_count} interview questions"
                        )

                    # FIRST: Delete project interviews that reference original interviews
                    project_interviews_count = ProjectInterview.query.filter(
                        ProjectInterview.original_interview_id.in_(
                            db.session.query(Interview.id).filter(
                                Interview.test_procedure_id == ts.id
                            )
                        )
                    ).delete(synchronize_session=False)
                    current_app.logger.info(
                        f"Deleted {project_interviews_count} project interviews"
                    )

                    # THEN: Delete original interviews
                    interview_count = Interview.query.filter_by(
                        test_procedure_id=ts.id
                    ).delete()
                    current_app.logger.info(f"Deleted {interview_count} interviews")

                    # Process document reviews
                    doc_reviews = DocumentReview.query.filter_by(
                        test_procedure_id=ts.id
                    ).all()
                    current_app.logger.info(
                        f"Found {len(doc_reviews)} document reviews"
                    )

                    for dr in doc_reviews:
                        # Delete project document reviews
                        pdr_count = ProjectDocumentReview.query.filter_by(
                            original_document_review_id=dr.id
                        ).delete()
                        current_app.logger.info(
                            f"Deleted {pdr_count} project document reviews"
                        )

                    # Delete document reviews
                    dr_count = DocumentReview.query.filter_by(
                        test_procedure_id=ts.id
                    ).delete()
                    current_app.logger.info(f"Deleted {dr_count} document reviews")

                # FIRST: Delete project test procedure files
                project_test_step_ids = [
                    pts.id
                    for pts in ProjectTestSteps.query.filter(
                        ProjectTestSteps.original_test_steps_id.in_(
                            db.session.query(TestSteps.id).filter(
                                TestSteps.control_id == control_act.id
                            )
                        )
                    ).all()
                ]

                if project_test_step_ids:
                    TestProcedureFile.query.filter(
                        TestProcedureFile.test_procedure_id.in_(project_test_step_ids)
                    ).delete(synchronize_session=False)
                    current_app.logger.info(
                        f"Deleted test procedure files for {len(project_test_step_ids)} project test steps"
                    )

                # THEN: Delete project test steps
                project_test_steps_count = ProjectTestSteps.query.filter(
                    ProjectTestSteps.original_test_steps_id.in_(
                        db.session.query(TestSteps.id).filter(
                            TestSteps.control_id == control_act.id
                        )
                    )
                ).delete(synchronize_session=False)
                current_app.logger.info(
                    f"Deleted {project_test_steps_count} project test steps"
                )

                # THEN: Delete original test steps
                ts_count = TestSteps.query.filter_by(control_id=control_act.id).delete()
                current_app.logger.info(f"Deleted {ts_count} test steps")

            # Get project control activity IDs for this control activity
            project_control_activity_ids = [
                pca.id
                for pca in ProjectControlActivity.query.filter(
                    ProjectControlActivity.original_control_id.in_(
                        db.session.query(ControlActivity.id).filter(
                            ControlActivity.compliance_activity_id == ca.id
                        )
                    )
                ).all()
            ]

            # FIRST: Delete project evidence files
            if project_control_activity_ids:
                # Get project evidence artifact IDs
                project_evidence_artifact_ids = [
                    pea.id
                    for pea in ProjectEvidenceArtifact.query.filter(
                        ProjectEvidenceArtifact.project_control_activity_id.in_(
                            project_control_activity_ids
                        )
                    ).all()
                ]

                # Delete evidence files
                if project_evidence_artifact_ids:
                    EvidenceFile.query.filter(
                        EvidenceFile.project_evidence_artifact_id.in_(
                            project_evidence_artifact_ids
                        )
                    ).delete(synchronize_session=False)
                    current_app.logger.info(
                        f"Deleted evidence files for {len(project_evidence_artifact_ids)} project evidence artifacts"
                    )

            # THEN: Delete project evidence artifacts
            project_evidence_count = ProjectEvidenceArtifact.query.filter(
                ProjectEvidenceArtifact.project_control_activity_id.in_(
                    project_control_activity_ids
                )
            ).delete(synchronize_session=False)
            current_app.logger.info(
                f"Deleted {project_evidence_count} project evidence artifacts"
            )

            # THEN: Delete project control activities
            project_control_count = ProjectControlActivity.query.filter(
                ProjectControlActivity.original_control_id.in_(
                    db.session.query(ControlActivity.id).filter(
                        ControlActivity.compliance_activity_id == ca.id
                    )
                )
            ).delete(synchronize_session=False)
            current_app.logger.info(
                f"Deleted {project_control_count} project control activities"
            )

            # THEN: Delete original control activities
            ca_count = ControlActivity.query.filter_by(
                compliance_activity_id=ca.id
            ).delete()
            current_app.logger.info(f"Deleted {ca_count} control activities")

            # CORRECTED: Delete HowToPerformActivity using activity_id (not compliance_activity_id)
            ht_count = HowToPerformActivity.query.filter_by(activity_id=ca.id).delete()
            current_app.logger.info(f"Deleted {ht_count} how-to-perform activities")

            # CORRECTED: Delete TestProcedures using activity_id (not compliance_activity_id)
            tp_count = TestProcedures.query.filter_by(activity_id=ca.id).delete()
            current_app.logger.info(f"Deleted {tp_count} test procedures")

            # CORRECTED: Delete Projects using activity_id (not compliance_activity_id)
            p_count = Projects.query.filter_by(activity=ca.id).delete()
            current_app.logger.info(f"Deleted {p_count} projects")

        # FIRST: Delete project compliance activities
        project_compliance_count = ProjectComplianceActivity.query.filter(
            ProjectComplianceActivity.original_activity_id.in_(
                db.session.query(ComplianceActivities.id).filter(
                    ComplianceActivities.clause_id == clause_id
                )
            )
        ).delete(synchronize_session=False)
        current_app.logger.info(
            f"Deleted {project_compliance_count} project compliance activities"
        )

        # THEN: Delete original compliance activities
        comp_count = ComplianceActivities.query.filter_by(clause_id=clause_id).delete()
        current_app.logger.info(f"Deleted {comp_count} compliance activities")

        # FIRST: Delete consolidated summaries for project clauses
        project_clause_ids = [
            pc.id
            for pc in ProjectClause.query.filter_by(original_clause_id=clause_id).all()
        ]

        if project_clause_ids:
            # Delete consolidated summaries
            ConsolidatedTestSummary.query.filter(
                ConsolidatedTestSummary.clause_id.in_(project_clause_ids)
            ).delete(synchronize_session=False)

            ConsolidatedObservationSummary.query.filter(
                ConsolidatedObservationSummary.clause_id.in_(project_clause_ids)
            ).delete(synchronize_session=False)

            ConsolidatedFindingsSummary.query.filter(
                ConsolidatedFindingsSummary.clause_id.in_(project_clause_ids)
            ).delete(synchronize_session=False)

            ConsolidatedRecommendationsSummary.query.filter(
                ConsolidatedRecommendationsSummary.clause_id.in_(project_clause_ids)
            ).delete(synchronize_session=False)

            ClauseConsolidatedSummary.query.filter(
                ClauseConsolidatedSummary.clause_id.in_(project_clause_ids)
            ).delete(synchronize_session=False)

            current_app.logger.info(
                f"Deleted consolidated summaries for {len(project_clause_ids)} project clauses"
            )

        # THEN: Delete project clauses
        project_clauses_count = ProjectClause.query.filter_by(
            original_clause_id=clause_id
        ).delete()
        current_app.logger.info(f"Deleted {project_clauses_count} project clauses")

        # Finally delete the clause
        db.session.delete(clause_to_delete)
        db.session.commit()

        current_app.logger.info(f"Successfully deleted clause {clause_id}")
        flash("Clause and all related records deleted successfully!", "success")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Error deleting clause {clause_id}: {str(e)}", exc_info=True
        )
        flash(f"Error deleting clause: {e}", "danger")

    return redirect(url_for("re.get_clause", guideline_id=guideline_id))


# bullk delete of the clauses route
@main_bp.route("/clauses/bulk-delete", methods=["POST"])
def bulk_delete_clauses():
    """
    Bulk delete multiple clauses and all their related records.
    """
    try:
        data = request.get_json()
        clause_ids = data.get("clause_ids", [])
        guideline_id = data.get("guideline_id")

        if not clause_ids:
            return jsonify({"success": False, "error": "No clause IDs provided"}), 400

        current_app.logger.info(f"Starting bulk deletion of {len(clause_ids)} clauses")

        deleted_count = 0
        errors = []

        for clause_id in clause_ids:
            try:
                clause_to_delete = Clauses.query.get(clause_id)
                if not clause_to_delete:
                    errors.append(f"Clause {clause_id} not found")
                    continue

                # Use the same deletion logic as single deletion
                # Find compliance activities
                compliance_activities = ComplianceActivities.query.filter_by(
                    clause_id=clause_id
                ).all()

                for ca in compliance_activities:
                    # Find control activities
                    control_activities = ControlActivity.query.filter_by(
                        compliance_activity_id=ca.id
                    ).all()

                    for control_act in control_activities:
                        # Delete entries from control_evidences many-to-many table
                        db.session.execute(
                            db.delete(control_evidences).where(
                                control_evidences.c.control_id == control_act.id
                            )
                        )

                        # Find test steps
                        test_steps = TestSteps.query.filter_by(
                            control_id=control_act.id
                        ).all()

                        for ts in test_steps:
                            # Process interviews
                            interviews = Interview.query.filter_by(
                                test_procedure_id=ts.id
                            ).all()

                            for interview in interviews:
                                # Delete project interview roles
                                ProjectInterviewRole.query.filter(
                                    ProjectInterviewRole.original_role_id.in_(
                                        db.session.query(InterviewRole.id).filter(
                                            InterviewRole.interview_id == interview.id
                                        )
                                    )
                                ).delete(synchronize_session=False)

                                # Delete original interview roles
                                InterviewRole.query.filter_by(
                                    interview_id=interview.id
                                ).delete()

                                # Delete project interview questions
                                ProjectInterviewQuestion.query.filter(
                                    ProjectInterviewQuestion.original_question_id.in_(
                                        db.session.query(InterviewQuestion.id).filter(
                                            InterviewQuestion.interview_id
                                            == interview.id
                                        )
                                    )
                                ).delete(synchronize_session=False)

                                # Delete original interview questions
                                InterviewQuestion.query.filter_by(
                                    interview_id=interview.id
                                ).delete()

                            # Delete project interviews
                            ProjectInterview.query.filter(
                                ProjectInterview.original_interview_id.in_(
                                    db.session.query(Interview.id).filter(
                                        Interview.test_procedure_id == ts.id
                                    )
                                )
                            ).delete(synchronize_session=False)

                            # Delete original interviews
                            Interview.query.filter_by(test_procedure_id=ts.id).delete()

                            # Process document reviews
                            doc_reviews = DocumentReview.query.filter_by(
                                test_procedure_id=ts.id
                            ).all()

                            for dr in doc_reviews:
                                # Delete project document reviews
                                ProjectDocumentReview.query.filter_by(
                                    original_document_review_id=dr.id
                                ).delete()

                            # Delete document reviews
                            DocumentReview.query.filter_by(
                                test_procedure_id=ts.id
                            ).delete()

                        # Delete project test steps
                        ProjectTestSteps.query.filter(
                            ProjectTestSteps.original_test_steps_id.in_(
                                db.session.query(TestSteps.id).filter(
                                    TestSteps.control_id == control_act.id
                                )
                            )
                        ).delete(synchronize_session=False)

                        # Delete original test steps
                        TestSteps.query.filter_by(control_id=control_act.id).delete()

                    # Delete project control activities
                    ProjectControlActivity.query.filter(
                        ProjectControlActivity.original_control_id.in_(
                            db.session.query(ControlActivity.id).filter(
                                ControlActivity.compliance_activity_id == ca.id
                            )
                        )
                    ).delete(synchronize_session=False)

                    # Delete original control activities
                    ControlActivity.query.filter_by(
                        compliance_activity_id=ca.id
                    ).delete()

                    # Delete other related entities
                    HowToPerformActivity.query.filter_by(activity_id=ca.id).delete()
                    TestProcedures.query.filter_by(activity_id=ca.id).delete()
                    Projects.query.filter_by(activity=ca.id).delete()

                # Delete project compliance activities
                ProjectComplianceActivity.query.filter(
                    ProjectComplianceActivity.original_activity_id.in_(
                        db.session.query(ComplianceActivities.id).filter(
                            ComplianceActivities.clause_id == clause_id
                        )
                    )
                ).delete(synchronize_session=False)

                # Delete original compliance activities
                ComplianceActivities.query.filter_by(clause_id=clause_id).delete()

                # Delete project clauses
                ProjectClause.query.filter_by(original_clause_id=clause_id).delete()

                # Finally delete the clause
                db.session.delete(clause_to_delete)
                deleted_count += 1

            except Exception as e:
                errors.append(f"Error deleting clause {clause_id}: {str(e)}")
                db.session.rollback()
                continue

        # Commit all changes
        db.session.commit()

        current_app.logger.info(f"Successfully deleted {deleted_count} clauses")

        if errors:
            return (
                jsonify(
                    {
                        "success": True,
                        "message": f"Deleted {deleted_count} clauses with {len(errors)} errors",
                        "errors": errors,
                    }
                ),
                207,
            )  # Multi-status

        return jsonify(
            {
                "success": True,
                "message": f"Successfully deleted {deleted_count} clauses",
            }
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in bulk deletion: {str(e)}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ================================================================


@main_bp.route("/api/task-status/<task_id>")
def task_status(task_id):
    """API endpoint to get task status for polling"""
    from celery.result import AsyncResult

    task_result = AsyncResult(task_id)

    response_data = {
        "state": task_result.state,
        "status": "PROCESSING",
        "progress": 0,
        "message": "Processing...",
    }

    if task_result.state == "PROGRESS":
        response_data.update(task_result.result)
    elif task_result.state == "SUCCESS":
        response_data.update(
            {
                "status": "COMPLETED",
                "progress": 100,
                "message": "Task completed successfully!",
            }
        )
    elif task_result.state == "FAILURE":
        response_data.update(
            {
                "status": "FAILED",
                "progress": 100,
                "message": f"Task failed: {str(task_result.info)}",
            }
        )

    return jsonify(response_data)


@main_bp.route("/my_profile")
@login_required
def my_profile():
    user = Users.query.get(current_user.id)

    if not user:
        flash("User not found.")
        return redirect(url_for("main.login"))

    # Ensure user has a profile
    if not user.profile:
        profile = UserProfiles(user_id=user.id)
        db.session.add(profile)
        db.session.commit()

    return render_template(
        "dashboards/auditor/my_profile.html", user=user, profile=user.profile
    )


@main_bp.route("/edit_profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    """Display and handle the edit profile form (user_edit_profile.html)."""
    user = Users.query.get(current_user.id)

    if not user:
        flash("User not found.", "error")
        return redirect(url_for("main.login"))

    # Ensure user has a profile
    if not user.profile:
        profile = UserProfiles(user_id=user.id)
        db.session.add(profile)
        db.session.commit()

    if request.method == "POST":
        try:
            # Update Users table fields
            user.name = request.form.get("name", user.name)
            user.email = request.form.get("email", user.email)

            # Handle phone number with country code
            country_code = request.form.get("phone_country_code", "+91")
            phone_number = request.form.get("phone_no", "")
            if phone_number:
                # Remove any existing country code from phone number
                phone_clean = phone_number.lstrip("+").lstrip("0")
                # Remove country code if it's already in the phone number
                for code in ["+91", "+1", "+44", "+61", "+81", "+971"]:
                    if phone_clean.startswith(code.lstrip("+")):
                        phone_clean = phone_clean[len(code.lstrip("+")) :]
                        break
                user.phone_no = f"{country_code}{phone_clean}"
            else:
                user.phone_no = request.form.get("phone_no", user.phone_no)

            # Update UserProfiles table fields
            profile = user.profile

            # Handle date fields properly
            date_of_birth = request.form.get("date_of_birth")
            if date_of_birth:
                from datetime import datetime

                profile.date_of_birth = datetime.strptime(
                    date_of_birth, "%Y-%m-%d"
                ).date()

            joining_date = request.form.get("joining_date")
            if joining_date:
                from datetime import datetime

                profile.joining_date = datetime.strptime(
                    joining_date, "%Y-%m-%d"
                ).date()

            # Update other profile fields
            profile.address = request.form.get("address", profile.address)
            profile.department = request.form.get("department", profile.department)
            profile.organization_name = request.form.get(
                "organization_name", profile.organization_name
            )
            profile.designation = request.form.get("designation", profile.designation)

            db.session.commit()
            flash("Profile updated successfully!", "success")
            return redirect(url_for("main.my_profile"))

        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred while updating your profile: {str(e)}", "error")
            return render_template(
                "dashboards/auditor/user_edit_profile.html", user=user
            )

    # GET request → pre-fill form with user data
    return render_template("dashboards/auditor/user_edit_profile.html", user=user)


@main_bp.route("/get_country")
def get_countries():
    """Returns a list of all countries."""
    countries = Country.query.all()
    country_names = [country.name for country in countries]
    return jsonify(country_names=country_names), 200


@main_bp.route("/states", methods=["GET"])
def get_states_by_country():
    """Returns a list of states for a specific country."""
    country_name = request.args.get("country_name")
    country = Country.query.filter_by(name=country_name).first()
    print(country_name, country)
    if not country:
        return jsonify(error="Country not found"), 404

    state_names = [state.state_name for state in country.states]
    return jsonify(state_names=state_names), 200


@main_bp.route("/cities", methods=["GET"])
def get_cities_by_state():
    """Returns a list of cities for a specific state."""
    state_name = request.args.get("state_name")
    state = State.query.filter_by(state_name=state_name).first()
    if not state:
        return jsonify(error="State not found"), 404

    city_names = [city.name for city in state.cities]
    return jsonify(city_names=city_names), 200


@main_bp.route("/create_prompt")
def create_new_prompt():
    prompt_types = PromptType
    print(prompt_types)

    return render_template("/dashboards/re/prompt_form.html", prompt_types=prompt_types)


@main_bp.route("/create_prompts", methods=["POST"])
def create_prompt():
    data = request.form

    required_fields = ["prompt_type", "prompt_text"]
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields"}), 400

    try:
        is_active = data.get("is_active") == "on"
        prompt_type_value_from_form = data["prompt_type"]

        # Convert form string to Enum
        prompt_type_enum = getattr(
            PromptType, prompt_type_value_from_form.upper(), None
        )
        if not prompt_type_enum:
            flash("Invalid prompt type submitted.", "error")
            return redirect(request.referrer)

        # 🔹 Auto-increment version
        latest_prompt = (
            AIPrompts.query.filter_by(prompt_type=prompt_type_enum.name)
            .order_by(AIPrompts.version.desc())
            .first()
        )
        next_version = (latest_prompt.version + 1) if latest_prompt else 1

        # Create new prompt
        new_prompt = AIPrompts(
            prompt_type=prompt_type_enum.name,
            prompt_text=data["prompt_text"],
            version=next_version,
            is_active=is_active,
            created_by=current_user.id,
        )

        db.session.add(new_prompt)
        db.session.commit()

        AIPrompts.query.filter(
            AIPrompts.prompt_type == new_prompt.prompt_type,
            AIPrompts.prompt_id != new_prompt.prompt_id,
        ).update({AIPrompts.is_active: False})

        db.session.commit()

        flash("Prompt created successfully!", "success")
        return redirect(url_for("main.view_prompts"))

    except Exception as e:
        db.session.rollback()
        print(e)
        flash(f"Something went wrong {e}", "error")
        return redirect(request.referrer)


@main_bp.route("/view_prompts")
def view_prompts():
    try:
        prompts = AIPrompts.query.all()
        # print(prompts)
        return render_template("dashboards/re/prompt_table.html", prompts=prompts)
    except Exception as e:
        flash(f"Something Went Wrong {e}", "error")
        return render_template("dashboards/re/prompt_table.html", prompts=[])


@main_bp.route("/delete_prompt/<int:prompt_id>", methods=["GET"])
def delete_prompt(prompt_id):
    try:
        prompt = AIPrompts.query.get(prompt_id)
        if not prompt:
            flash("Prompt not found", "error")
            return redirect(request.referrer)

        db.session.delete(prompt)
        db.session.commit()

        flash("Prompt deleted successfully", "success")
    except Exception as err:
        db.session.rollback()
        current_app.logger.error(f"Error deleting prompt {prompt_id}: {str(err)}")
        flash("Error deleting prompt", "error")

    return redirect(request.referrer)


@main_bp.route("/edit_prompt/<int:prompt_id>", methods=["GET", "POST"])
def edit_prompt(prompt_id):
    prompt = AIPrompts.query.get_or_404(prompt_id)

    if request.method == "POST":
        try:
            prompt.prompt_type = request.form.get("prompt_type")
            prompt.prompt_text = request.form.get("prompt_text")
            db.session.commit()
            flash("Prompt updated successfully!", "success")
            return redirect(
                url_for("main.view_prompts")
            )  # Redirect to your main audit page
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating prompt: {e}", "danger")
            return redirect(url_for("main.view_prompts", prompt_id=prompt_id))

    return render_template("dashboards/re/edit_prompt.html", prompt=prompt)


@main_bp.route("/toggle_prompt/<int:prompt_id>", methods=["POST"])
@login_required
def toggle_prompt(prompt_id):
    try:
        # Get the prompt to toggle
        prompt = AIPrompts.query.get_or_404(prompt_id)
        # Activate this prompt
        prompt.is_active = True

        # Deactivate all other versions of the same prompt_type
        AIPrompts.query.filter(
            AIPrompts.prompt_type == prompt.prompt_type,
            AIPrompts.prompt_id != prompt_id,
        ).update({AIPrompts.is_active: False})

        db.session.commit()

        return jsonify(
            {
                "status": "success",
                "message": f"Prompt {prompt.prompt_id} activated, other versions deactivated.",
            }
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error toggling prompt: {str(e)}")
        return jsonify({"status": "error", "message": "Something went wrong"}), 500
