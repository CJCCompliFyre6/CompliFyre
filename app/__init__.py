# backend/app/__init__.py
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix, send_from_directory, redirect, url_for, current_app
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from dotenv import load_dotenv
import os
from openai import AzureOpenAI
from flask_login import LoginManager, current_user, login_required
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_admin import Admin, AdminIndexView
from flask_admin.contrib.sqla import ModelView
from flask_misaka import Misaka
from config import config_by_name
from celery_app import celery_init_app
from flask_mail import Mail
from flask_session import Session
  

# -----------------------------------------------------------------------------
# Extension Initialization
# -----------------------------------------------------------------------------
db = SQLAlchemy()
migrate = Migrate()
md = Misaka()
login_manager = LoginManager()
mail = Mail()
sess = Session()
csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=None,
    strategy="fixed-window",
    default_limits=[],
)

AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")
client = AzureOpenAI(api_key=AZURE_OPENAI_API_KEY, azure_endpoint=AZURE_OPENAI_ENDPOINT, api_version=AZURE_OPENAI_API_VERSION, timeout=120.0)

# -----------------------------------------------------------------------------
# Flask-Login Configuration
# -----------------------------------------------------------------------------
@login_manager.user_loader
def load_user(user_id):
    """Flask-Login hook to load a user from the database by ID."""
    try:
        # Use lazy imports inside the function to avoid circular imports
        from app.models.user import Users
        from app.models.organization import OrganizationContacts
        
        # First try to load as regular User
        user = Users.query.get(int(user_id))
        if user:
            return user
        
        # If not found, try as OrganizationContact
        org_contact = OrganizationContacts.query.get(int(user_id))
        if org_contact:
            return org_contact
        
        # If neither found, return None
        return None
        
    except Exception as e:
        current_app.logger.error(f"Error loading user {user_id}: {str(e)}")
        return None

# -----------------------------------------------------------------------------
# Application Factory
# -----------------------------------------------------------------------------
def create_app(config_name=None):
    """
    Creates and configures an instance of the Flask application.
    This is the application factory pattern.
    """
    if config_name is None:
        config_name = os.getenv('FLASK_ENV', 'default')
    
    load_dotenv()

    # --- Admin View Classes for Access Control ---
    class MyAdminIndexView(AdminIndexView):
        def is_accessible(self):
            """
            Checks if the current user is authenticated and has the 'ADMIN' role.
            """
            return (
                current_user.is_authenticated and
                current_user.role and
                current_user.role.name == 'ADMIN'
            )

        def inaccessible_callback(self, name, **kwargs):
            """Redirects non-admins to the login page."""
            return redirect(url_for('main.login'))

    class MyModelView(ModelView):
        def is_accessible(self):
            """
            Checks if the current user is authenticated and has the 'ADMIN' role.
            """
            return (
                current_user.is_authenticated and
                current_user.role and
                current_user.role.name == 'ADMIN'
            )

        def inaccessible_callback(self, name, **kwargs):
            """Redirects non-admins to the login page."""
            return redirect(url_for('main.login'))

    # --- App Creation and Configuration ---
    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])
    
    # --- Initialize Extensions with the App ---
    admin = Admin(app, name='Complifyre Admin', template_mode='bootstrap4', index_view=MyAdminIndexView())    
    
    login_manager.init_app(app)
    login_manager.login_view = 'main.login'
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "info"

    CORS(app)
    db.init_app(app)
    migrate.init_app(app, db)
    md.init_app(app)
    mail.init_app(app)
    sess.init_app(app)
    csrf.init_app(app)
    app.config["RATELIMIT_STORAGE_URI"] = app.config.get("CELERY", {}).get("broker_url") or "redis://127.0.0.1:6379/0"
    limiter.init_app(app)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # S-71: trust Nginx X-Real-IP

    # --- Initialize Celery ---
    celery_app = celery_init_app(app)
    app.extensions["celery"] = celery_app


     # Initialize TaskStatus AFTER app is created
    from app.models.task_status import TaskStatus
    task_status = TaskStatus()
    task_status.init_app(app)
    app.task_status = task_status

    # --- Static File Route ---
    @app.route('/files/<path:filename>')
    @login_required
    def uploaded_file(filename):
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        app.config['UPLOAD_FOLDER_EVIDENCE'] = os.path.join(BASE_DIR, "../uploads")
        return send_from_directory(app.config['UPLOAD_FOLDER_EVIDENCE'], filename, as_attachment=True)  # S-63: force download, prevent inline PDF JS execution
    

    
    # --- Register Admin Views ---
    from app.models import (
        AIPrompts, Attachments, AuditLogs, AuditEngagements, AuditControls,
        ControlRegulationMapping, AuditTestingTemplates, AuditEvidence,
        AuditReportTemplates, AuditReports, ChatSessions, ChatMessages,
        Dashboards, DashboardWidgets, Download, File, Prompts, Organizations,
        OrganizationAddresses, OrganizationContacts, OrganizationInfo,
        OrganizationLicenses, OrganizationComplianceProfiles, OrganizationBranches,
        OrganizationDepartments, Country, State, City, Policies, PolicyApprovals,
        RegulatoryBodies, DocumentCategories, RegulatoryDocuments,
        RegulationDependencies, Tasks, TaskComments, TaskEscalations, UserTypes,
        Roles, Users, Clauses, Guidelines, AuditOrgContactPerson, Projects,
        ComplianceActivities, OrganizationType, Constitution, GuidelineRequest,
    )
    from app.models.eve_models import (
        GuidelineEveContext,
        ControlChecklist,
        ProjectChecklist,
        EveEvidenceResult,
        EveControlResult,
    )

    class UserTypesView(ModelView):
        form_excluded_columns = ['created_at']

    admin.add_view(UserTypesView(UserTypes, db.session))
    admin.add_view(MyModelView(Roles, db.session))    
    admin.add_view(MyModelView(Users, db.session))
    admin.add_view(MyModelView(Organizations, db.session))
    admin.add_view(MyModelView(OrganizationAddresses, db.session))
    admin.add_view(MyModelView(OrganizationContacts, db.session))
    admin.add_view(MyModelView(OrganizationInfo, db.session))
    admin.add_view(MyModelView(OrganizationLicenses, db.session))
    admin.add_view(MyModelView(OrganizationComplianceProfiles, db.session))
    admin.add_view(MyModelView(OrganizationBranches, db.session))
    admin.add_view(MyModelView(OrganizationDepartments, db.session))
    admin.add_view(MyModelView(Country, db.session))
    admin.add_view(MyModelView(State, db.session))
    admin.add_view(MyModelView(City, db.session))
    admin.add_view(MyModelView(Policies, db.session))
    admin.add_view(MyModelView(PolicyApprovals, db.session))
    admin.add_view(MyModelView(RegulatoryBodies, db.session))
    admin.add_view(MyModelView(DocumentCategories, db.session))
    admin.add_view(MyModelView(RegulatoryDocuments, db.session))
    admin.add_view(MyModelView(RegulationDependencies, db.session))
    admin.add_view(MyModelView(AIPrompts, db.session))
    admin.add_view(MyModelView(Attachments, db.session))
    admin.add_view(MyModelView(AuditLogs, db.session))
    admin.add_view(MyModelView(AuditEngagements, db.session))
    admin.add_view(MyModelView(AuditControls, db.session))
    admin.add_view(MyModelView(ControlRegulationMapping, db.session))
    admin.add_view(MyModelView(AuditTestingTemplates, db.session))
    admin.add_view(MyModelView(AuditEvidence, db.session))
    admin.add_view(MyModelView(AuditReportTemplates, db.session))
    admin.add_view(MyModelView(AuditReports, db.session))
    admin.add_view(MyModelView(ChatSessions, db.session))
    admin.add_view(MyModelView(ChatMessages, db.session))
    admin.add_view(MyModelView(Dashboards, db.session))
    admin.add_view(MyModelView(DashboardWidgets, db.session))
    admin.add_view(MyModelView(File, db.session))
    admin.add_view(MyModelView(Prompts, db.session))
    admin.add_view(MyModelView(Tasks, db.session))
    admin.add_view(MyModelView(TaskComments, db.session))
    admin.add_view(MyModelView(TaskEscalations, db.session))
    admin.add_view(MyModelView(Clauses, db.session))
    admin.add_view(MyModelView(Guidelines, db.session))
    admin.add_view(MyModelView(AuditOrgContactPerson, db.session))
    admin.add_view(MyModelView(ComplianceActivities, db.session))
    admin.add_view(MyModelView(Projects, db.session))
    admin.add_view(MyModelView(OrganizationType, db.session))
    admin.add_view(MyModelView(Constitution, db.session))
    admin.add_view(MyModelView(GuidelineEveContext, db.session))
    admin.add_view(MyModelView(ControlChecklist, db.session))
    admin.add_view(MyModelView(ProjectChecklist, db.session))
    admin.add_view(MyModelView(EveEvidenceResult, db.session))
    admin.add_view(MyModelView(EveControlResult, db.session))

    # --- Register Blueprints ---
    from app.routes.download import download_bp
    from app.routes.retrival import retrival_bp
    from app.routes.prompts import prompt_bp
    from app.routes.re.view import re_bp
    from app.routes.re.eve_routes import eve_re_bp
    from app.routes.audit.view import audit_bp
    from app.routes.audit.eve_audit_routes import eve_audit_bp
    from app.routes.audit.location_routes import location_bp
    from app.routes.main import main_bp
    from app.routes.notifications import notifications_bp

    app.register_blueprint(download_bp, url_prefix="/api/download")
    app.register_blueprint(retrival_bp, url_prefix="/api/retrive")
    app.register_blueprint(prompt_bp, url_prefix="/api/prompt")
    app.register_blueprint(re_bp, url_prefix="/re")
    from app.routes.loi.view import loi_bp
    app.register_blueprint(loi_bp, url_prefix="/loi")
    app.register_blueprint(eve_re_bp)
    app.register_blueprint(audit_bp, url_prefix="/audit")
    app.register_blueprint(eve_audit_bp)
    app.register_blueprint(location_bp, url_prefix="/api")
    app.register_blueprint(notifications_bp, url_prefix="/api/notifications")
    app.register_blueprint(main_bp)

    # --- Database Creation ---
    with app.app_context():
        db.create_all()
    
    # --- Register Custom CLI Commands ---
    from app.command_cli import register_cli_commands
    register_cli_commands(app)

   
    
    return app

