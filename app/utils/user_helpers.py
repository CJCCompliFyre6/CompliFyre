from app import db
from app.models.user import Users
import secrets

def create_user_for_contact(name, email, phone, temp_password, audit_org_id):
    """
    Create user that matches your actual Users model structure
    NOTE: Changed parameter from organization_id to audit_org_id
    """
    try:
        print(f"🔧 Creating user for: {name} ({email})")
        
        if not email:
            print("❌ No email provided for user creation")
            return None

        # Check if user already exists with this email
        existing_user = Users.query.filter_by(email=email).first()
        if existing_user:
            print(f"⚠️ User already exists with email: {email}")
            print(f"⚠️ Existing user ID: {existing_user.id}")
            # Update existing user with correct fields
            existing_user.role_id = 1  # Auditor role ID
            existing_user.auditor_profile_id = audit_org_id  # Use audit_org_id
            existing_user.status = "active"
            existing_user.email_verified = True
            if not existing_user.check_password(temp_password):
                existing_user.set_password(temp_password)
            db.session.add(existing_user)
            return existing_user
        
        # Create new user with correct field names
        user = Users()
        user.email = email
        user.name = name
        user.phone_no = phone
        user.role_id = 1
        user.auditor_profile_id = audit_org_id  # Use audit_org_id
        user.email_verified = True
        user.status = "active"
        user.tfa_enabled = True
        
        # Set password
        user.set_password(temp_password)
        
        # Generate session token that fits in 36 characters
        user.session_token = secrets.token_urlsafe(24)
        
        # DEBUG: Print all user data before adding to session
        print(f"🔍 DEBUG - User object before add:")
        print(f"  Email: {user.email}")
        print(f"  Name: {user.name}")
        print(f"  Phone: {user.phone_no}")
        print(f"  Role ID: {user.role_id}")
        print(f"  Auditor Profile ID: {user.auditor_profile_id}")
        print(f"  Status: {user.status}")
        print(f"  Session Token Length: {len(user.session_token)}")
        
        # Add to session
        db.session.add(user)
        
        print(f"✅ Successfully created User record for: {email}")
        return user
        
    except Exception as e:
        print(f"❌ Error creating user: {str(e)}")
        import traceback
        print(f"❌ Full traceback: {traceback.format_exc()}")
        return None

def create_user_direct_sql_fixed(name, email, phone, temp_password, audit_org_id):
    """
    Create user using direct SQL that matches your actual schema
    NOTE: Changed parameter from organization_id to audit_org_id
    """
    try:
        print(f"🔧 Creating user via SQL for: {name} ({email})")
        
        if not email:
            print("❌ No email provided for user creation")
            return None

        # Check if user exists
        existing_user = Users.query.filter_by(email=email).first()
        if existing_user:
            print(f"⚠️ User already exists with email: {email}")
            return existing_user

        # Generate password hash
        from werkzeug.security import generate_password_hash
        password_hash = generate_password_hash(temp_password)
        
        # Generate session token that fits in 36 characters
        session_token = secrets.token_urlsafe(24)

        # Direct SQL insertion that matches your schema
        from sqlalchemy import text
        sql = text("""
            INSERT INTO "Users" 
            (email, name, phone_no, role_id, password_hash, email_verified, status, 
             auditor_profile_id, session_token, tfa_enabled, created_at, updated_at)
            VALUES 
            (:email, :name, :phone_no, :role_id, :password_hash, true, 'active',
             :auditor_profile_id, :session_token, True, NOW(), NOW())
            RETURNING id
        """)
        
        result = db.session.execute(sql, {
            'email': email,
            'name': name,
            'phone_no': phone,
            'role_id': 1,
            'password_hash': password_hash,
            'auditor_profile_id': audit_org_id,  # Use audit_org_id
            'session_token': session_token
        })
        
        # Get the created user
        user_id = result.fetchone()[0]
        user = Users.query.get(user_id)
        
        print(f"✅ Successfully created User via SQL for: {email}")
        return user
        
    except Exception as e:
        print(f"❌ Error creating user via SQL: {str(e)}")
        return None