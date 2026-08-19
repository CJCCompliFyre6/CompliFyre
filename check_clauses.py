import re
from run import app
from app.models.ai import Clauses

with app.app_context():
    rows = Clauses.query.filter_by(guideline_id=202).filter(Clauses.clause_text.like('%per cent%')).all()
    print("Total clauses with 'per cent':", len(rows))
    for r in rows:
        matches = [m.group() for m in re.finditer(r'.{15}per cent', r.clause_text)]
        print(r.clause_no, "|", matches)
