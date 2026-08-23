import shutil

path = "app/models/__init__.py"
with open(path) as f:
    content = f.read()

old = "from .task_status import *\n"
new = '''from .task_status import *
from .loi import (
    SignupInvites,
    InvitePreloadGuidelines,
    LoiTemplates,
    LoiSignatures,
    UserJourneyEvents,
    LoiForwardRequests,
    ExtensionRequests,
    EditableContent,
    LoiTriggerConfig,
    LoiGlobalConfig,
    GuidelineBundles,
    GuidelineBundleItems,
)
'''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_pre_loi_models_import")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched models/__init__.py (backup at __init__.py.bak_pre_loi_models_import)")
