from functools import wraps
from flask import request, redirect, url_for, abort
from flask_login import current_user
from app.models.user import Roles
import json
from flask import g, redirect, url_for, flash

# def role_required():
#     def decorator(f):
#         @wraps(f)
#         def decorated_function(*args, **kwargs):
#             if not current_user.is_authenticated:
#                 return redirect(url_for('re.login'))  # or your login route

#             # Assuming user.role is a relationship or has role_id
#             role = Roles.query.get(current_user.role_id)
#             print(role)
#             if not role:
#                 return abort(403)

#             # Permissions should be a JSON object like {"USER": ["/user", "/profile/form"]}
#             permissions = role.permissions or {}
#             print(permissions, type(permissions))
#             if isinstance(permissions, str):
#                 permissions = json.loads(permissions)

#             endpoint_path = request.path
#             print(endpoint_path)
#             print([perm_list for perm_list in permissions.values()])
#             has_permission = any(endpoint_path in perm_list for perm_list in permissions.values())
#             print(has_permission)
#             if not has_permission:
#                 return abort(403)  # Forbidden

#             return f(*args, **kwargs)
#         return decorated_function
#     return decorator

def list_routes(app):
    output = []
    for rule in app.url_map.iter_rules():
        methods = ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))  # exclude common defaults
        endpoint = rule.endpoint
        url = str(rule)
        output.append({'endpoint': endpoint, 'methods': methods, 'url': url})
    return output


def role_required(*roles):
    """
    Decorator to restrict access to a route based on user roles.

    Args:
        *roles: A variable number of strings representing the allowed roles.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Check if the user is authenticated and has a role
            if not current_user.is_authenticated or not current_user.role:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for('main.login')) # Assuming a login route

            # Check if the user's role name is in the allowed roles
            if current_user.role.name not in roles:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for('main.home')) # Redirect to a safe page

            return f(*args, **kwargs)
        return decorated_function
    return decorator
