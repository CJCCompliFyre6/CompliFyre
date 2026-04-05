from flask import session, request

def add_to_breadcrumb(url, title):
    """
    Add a page to the breadcrumb trail with intelligent navigation handling.
    
    Args:
        url: The URL to add (can be relative or full path)
        title: The display title for this breadcrumb item
    """
    # Use full_path (includes ?query) if provided, else from request
    current_url = url if url else request.full_path

    # --- Normalize (strip query params) ---
    clean_path = request.path if not url else url.split("?")[0]

    # --- RESET only when exact /audit/ is visited ---
    if clean_path == "/audit/":
        session['breadcrumb'] = [{'url': '/audit/', 'title': 'Auditor Dashboard'}]
        session.modified = True
        return

    # Initialize breadcrumb if it doesn't exist
    if 'breadcrumb' not in session or not session['breadcrumb']:
        session['breadcrumb'] = [{'url': '/audit/', 'title': 'Auditor Dashboard'}]

    # Don't add duplicate consecutive entries
    if session['breadcrumb'] and session['breadcrumb'][-1]['url'] == current_url:
        return

    # Check if this URL already exists in the breadcrumb trail
    found_index = next((i for i, item in enumerate(session['breadcrumb']) if item['url'] == current_url), -1)

    if found_index != -1:
        # Truncate breadcrumb at that point
        session['breadcrumb'] = session['breadcrumb'][:found_index + 1]
    else:
        # Add new breadcrumb item
        session['breadcrumb'].append({'url': current_url, 'title': title})

    # Limit breadcrumb length (keep Dashboard + 10 pages max)
    if len(session['breadcrumb']) > 11:
        session['breadcrumb'].pop(1)

    session.modified = True


def get_breadcrumb():
    """Get the current breadcrumb trail."""
    if 'breadcrumb' not in session:
        return [{'url': '/audit/', 'title': 'Auditor Dashboard'}]
    return session['breadcrumb']


def clear_breadcrumb():
    """Clear the breadcrumb trail (reset to just Dashboard)."""
    session['breadcrumb'] = [{'url': '/audit/', 'title': 'Auditor Dashboard'}]
    session.modified = True
