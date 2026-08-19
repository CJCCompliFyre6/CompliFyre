from app import db
from sqlalchemy import text

tables_and_pk = [
    ('Organizations', 'organization_id'),
    ('signup_invites', 'id'),
    ('invite_preload_guidelines', 'id'),
    ('loi_signatures', 'id'),
    ('guidelines', 'id'),
]

for table, pk in tables_and_pk:
    try:
        max_id = db.session.execute(text(f'SELECT MAX("{pk}") FROM "{table}"')).scalar()
        seq_name = db.session.execute(text(f"SELECT pg_get_serial_sequence('\"{table}\"', '{pk}')")).scalar()
        if seq_name is None:
            print(table, '-- no sequence found (max id:', max_id, ')')
        else:
            seq_val = db.session.execute(text(f'SELECT last_value FROM {seq_name}')).scalar()
            status = 'OK' if (max_id is None or seq_val >= max_id) else 'DESYNCED'
            print(table, '| max(id):', max_id, '| sequence:', seq_val, '|', status)
    except Exception as e:
        print(table, '-- ERROR:', str(e))
        db.session.rollback()

print('DONE')
