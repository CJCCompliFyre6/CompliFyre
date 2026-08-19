import shutil

path = "app/templates/dashboards/re/audit_base.html"
with open(path) as f:
    content = f.read()

anchor = '<div class="footer relative my-8">'
count = content.count(anchor)
print(f"Anchor '<div class=\"footer relative my-8\">' occurs {count} time(s) in the file")

if count != 1:
    print("WARNING: anchor is not unique. No edit made -- need a different approach.")
else:
    insertion = '''        <li class="submenu">
          <a href="#" onclick="toggleSubmenu(event)">
            <i class="bx bx-user-plus"></i> Invite New User <i class="bx bx-chevron-down"></i>
          </a>
          <ul class="submenu-items">
            <li><a href="{{ url_for('loi.invite_new_user_form') }}">Send New Invite</a></li>
            <li><a href="{{ url_for('loi.invite_list') }}">Invitations</a></li>
          </ul>
        </li>
      </ul>
      '''
    # Find the </ul> immediately preceding the anchor and replace from there
    anchor_pos = content.find(anchor)
    # search backwards from anchor_pos for the nearest "</ul>" before it
    preceding = content[:anchor_pos]
    ul_pos = preceding.rfind("</ul>")
    if ul_pos == -1:
        print("WARNING: could not find a preceding </ul> before the anchor. No edit made.")
    else:
        before = content[:ul_pos]
        after = content[ul_pos + len("</ul>"):]
        # after should just be whitespace up to the anchor
        gap = after[:anchor_pos - (ul_pos + len("</ul>"))]
        print("Gap between </ul> and anchor (repr):", repr(gap))
        shutil.copy(path, path + ".bak_pre_invite_nav_link_v2")
        new_content = before + insertion + content[anchor_pos:]
        with open(path, "w") as f:
            f.write(new_content)
        print("Patched audit_base.html (backup at audit_base.html.bak_pre_invite_nav_link_v2)")
