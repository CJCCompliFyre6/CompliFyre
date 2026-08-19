import shutil

path = "app/templates/dashboards/loi/activation_form.html"
with open(path) as f:
    content = f.read()

old = '''        <label class="block mb-1 text-sm font-medium text-gray-700">Entity Type *</label>
        <select name="entity_type" required class="w-full border rounded-lg p-2 mb-4">
            <option value="">Select...</option>
            {% for et in entity_types %}
            <option value="{{ et }}">{{ et }}</option>
            {% endfor %}
        </select>

        <label class="block mb-1 text-sm font-medium text-gray-700">CIN *</label>
        <input type="text" name="cin" required class="w-full border rounded-lg p-2 mb-4">

        <label class="block mb-1 text-sm font-medium text-gray-700">Kindly provide full office address *</label>
        <textarea name="registered_address" required class="w-full border rounded-lg p-2 mb-4"></textarea>

        <div class="grid grid-cols-2 gap-4 mb-4">
            <div>
                <label class="block mb-1 text-sm font-medium text-gray-700">City *</label>
                <input type="text" name="city" required class="w-full border rounded-lg p-2">
            </div>
            <div>
                <label class="block mb-1 text-sm font-medium text-gray-700">State *</label>
                <input type="text" name="state" required class="w-full border rounded-lg p-2">
            </div>
        </div>'''

new = '''        <label class="block mb-1 text-sm font-medium text-gray-700">Entity Type *</label>
        {% if parent_org %}
        <input type="text" value="{{ parent_org.entity_type }}" readonly class="w-full border rounded-lg p-2 mb-4 bg-gray-100 text-gray-500">
        {% else %}
        <select name="entity_type" required class="w-full border rounded-lg p-2 mb-4">
            <option value="">Select...</option>
            {% for et in entity_types %}
            <option value="{{ et }}">{{ et }}</option>
            {% endfor %}
        </select>
        {% endif %}

        <label class="block mb-1 text-sm font-medium text-gray-700">CIN *</label>
        {% if parent_org %}
        <input type="text" name="cin" value="{{ parent_org.cin }}" readonly class="w-full border rounded-lg p-2 mb-4 bg-gray-100 text-gray-500">
        {% else %}
        <input type="text" name="cin" required class="w-full border rounded-lg p-2 mb-4">
        {% endif %}

        <label class="block mb-1 text-sm font-medium text-gray-700">Kindly provide full office address *</label>
        {% if parent_org %}
        <textarea readonly class="w-full border rounded-lg p-2 mb-4 bg-gray-100 text-gray-500">{{ parent_org.registered_address }}</textarea>
        {% else %}
        <textarea name="registered_address" required class="w-full border rounded-lg p-2 mb-4"></textarea>
        {% endif %}

        <div class="grid grid-cols-2 gap-4 mb-4">
            <div>
                <label class="block mb-1 text-sm font-medium text-gray-700">City *</label>
                {% if parent_org %}
                <input type="text" value="{{ parent_org.city }}" readonly class="w-full border rounded-lg p-2 bg-gray-100 text-gray-500">
                {% else %}
                <input type="text" name="city" required class="w-full border rounded-lg p-2">
                {% endif %}
            </div>
            <div>
                <label class="block mb-1 text-sm font-medium text-gray-700">State *</label>
                {% if parent_org %}
                <input type="text" value="{{ parent_org.state }}" readonly class="w-full border rounded-lg p-2 bg-gray-100 text-gray-500">
                {% else %}
                <input type="text" name="state" required class="w-full border rounded-lg p-2">
                {% endif %}
            </div>
        </div>'''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_activation_form_parent_org")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched activation_form.html (backup at .bak_activation_form_parent_org)")
