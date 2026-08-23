# app/models/user.py

from app import db
from sqlalchemy import Enum
from sqlalchemy.sql import func
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import enum


class UserTypes(db.Model):
    """Defines types of users in the system, e.g., 'Client', 'Auditor'."""
    __tablename__ = "UserTypes"
    type_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    type_name = db.Column(
        db.String(50), nullable=False, unique=True
    )
    description = db.Column(db.Text)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())


class Roles(db.Model):
    """Defines user roles and their permissions, e.g., 'Admin', 'Manager'."""
    __tablename__ = "Roles"
    role_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    description = db.Column(db.Text)
    permissions = db.Column(db.JSON)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class Users(db.Model, UserMixin):
    """
    Represents a user account. Deleting a user will also delete their associated profile.
    """
    __tablename__ = "Users"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id")
    )
    auditor_profile_id = db.Column(
        db.BigInteger, db.ForeignKey('AuditOrganization.id'), nullable=True
    )
    email = db.Column(db.String(255), nullable=False, unique=True)
    phone_no = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    role_id = db.Column(db.BigInteger, db.ForeignKey("Roles.role_id"))
    password_hash = db.Column(db.String(255), nullable=False)
    email_verified = db.Column(db.Boolean, default=False)
    phone_no_verified = db.Column(db.Boolean, default=False)
    free_report_used = db.Column(db.Boolean, default=False)
    invite_id = db.Column(db.BigInteger, nullable=True)
    designation = db.Column(db.String(100), nullable=True)

    invite_id = db.Column(db.BigInteger, nullable=True)
    designation = db.Column(db.String(100), nullable=True)
    # +++ ADDED FOR NEW FEATURES +++
    tfa_secret = db.Column(db.String(255), nullable=True)
    tfa_enabled = db.Column(db.Boolean, default=False)
    session_token = db.Column(db.String(36), nullable=True, unique=True)
    # ++++++++++++++++++++++++++++++

    status = db.Column(
        Enum("active", "inactive", "suspended", name="user_status_enum"), 
        default="active"
    )
    last_login = db.Column(db.TIMESTAMP)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    organization = db.relationship("Organizations", backref="users")
    role = db.relationship("Roles", backref="users")
    auditor_profile = db.relationship("AuditOrganization", backref="Users")
    profile = db.relationship(
        "UserProfiles", 
        back_populates="user", 
        uselist=False, 
        cascade="all, delete-orphan"
    )

    
    
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def get_id(self):
        return str(self.id)


class UserProfiles(db.Model):
    """Stores additional, non-critical information for a user."""
    __tablename__ = "UserProfiles"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("Users.id"), nullable=False, unique=True)

    date_of_birth = db.Column(db.Date, nullable=True)
    address = db.Column(db.String(255), nullable=True)
    designation = db.Column(db.String(100), nullable=True)
    department = db.Column(db.String(100), nullable=True)
    organization_name = db.Column(db.String(150), nullable=True)
    joining_date = db.Column(db.Date, nullable=True)

    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp()
    )

    user = db.relationship("Users", back_populates="profile")



# ====================================Rebuilding=====================================

# class UserType(enum.Enum):
#     COMPLIFYRE = 'complifyre'
#     AUDITOR    = 'AUDITOR'
#     RE         = 're'
#     REGULATOR  = 'regulator'


# class UserStatus(enum.Enum):
#     ACTIVE='active'
#     INACTIVE='inactive'
#     SUSPENDED='suspended'

# class UserModule(db.Model, UserMixin):
#     __tablename__='usermodule'
#     id = db.Column(db.BigInteger, primary_keys=True, autoincrement=True)
#     usertype = db.Column(db.Enum(UserType), nullable=False, default=UserType.COMPLIFYRE)
#     email = db.Column(db.String(255), nullable=False, unique=True)
#     phone_no = db.Column(db.String(20), nullable=False)
#     full_name = db.Column(db.String(100), nullable=False)
#     lastname = db.Column(db.String(100), nullable=False)
#     password_hash = db.Column(db.String(255), nullable=False)
#     status = db.Column(db.Enum(UserStatus), nullable=False, default=UserStatus.ACTIVE)
#     last_login = db.Column(db.TIMESTAMP)
#     created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
#     updated_at = db.Column(
#         db.TIMESTAMP,
#         default=func.current_timestamp(),
#         onupdate=func.current_timestamp(),
#     )

#     def __repr__(self):
#         return f"<User {self.email}>"




    