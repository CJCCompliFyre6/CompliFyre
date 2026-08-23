import shutil

path = "app/templates/dashboards/re/audit_base.html"
with open(path) as f:
    content = f.read()

old = '''        {%endif%}
      </ul>
      <div class="footer relative my-8">'''

new = '''        {%endif%}
        <li class="submenu">
          <a href="#" onclick="toggleSubmenu(event)">
            <i class="bx bx-user-plus"></i> Invite New User <i class="bx bx-chevron-down"></i>
          </a>
          <ul class="submenu-items">
            <li><a href="{{ url_for('loi.invite_new_user_form') }}">Send New Invite</a></li>
            <li><a href="{{ url_for('loi.invite_list') }}">Invitations</a></li>
          </ul>
        </li>
      </ul>
      <div class="footer relative my-8">'''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_pre_invite_nav_link")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched audit_base.html (backup at audit_base.html.bak_pre_invite_nav_link)")
