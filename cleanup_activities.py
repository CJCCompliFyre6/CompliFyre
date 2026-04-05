from app import create_app
app = create_app()
with app.app_context():
    from app import db
    from sqlalchemy import text

    problem_clauses = db.session.execute(text('''
        SELECT c.id, c.clause_no, COUNT(ca.id) as cnt
        FROM clauses c
        JOIN compliance_activities ca ON ca.clause_id = c.id
        WHERE c.guideline_id = 141
        GROUP BY c.id, c.clause_no
        HAVING COUNT(ca.id) > 8
        ORDER BY cnt DESC
    ''')).fetchall()

    total_deleted = 0
    for clause in problem_clauses:
        clause_id, clause_no, count = clause[0], clause[1], clause[2]

        all_acts = db.session.execute(text(
            'SELECT id FROM compliance_activities WHERE clause_id = :cid ORDER BY id'
        ), {'cid': clause_id}).fetchall()

        delete_comp_ids = [r[0] for r in all_acts[6:]]
        if not delete_comp_ids:
            continue

        ctrl_ids = db.session.execute(text(
            'SELECT id FROM control_activities WHERE compliance_activity_id = ANY(:ids)'
        ), {'ids': delete_comp_ids}).fetchall()
        ctrl_ids = [r[0] for r in ctrl_ids]

        if ctrl_ids:
            ts_ids = db.session.execute(text(
                'SELECT id FROM test_steps WHERE control_id = ANY(:ids)'
            ), {'ids': ctrl_ids}).fetchall()
            ts_ids = [r[0] for r in ts_ids]

            if ts_ids:
                # interview_roles → interviews → test_steps chain
                interview_ids = db.session.execute(text(
                    'SELECT id FROM interviews WHERE test_procedure_id = ANY(:ids)'
                ), {'ids': ts_ids}).fetchall()
                interview_ids = [r[0] for r in interview_ids]

                if interview_ids:
                    db.session.execute(text(
                        'DELETE FROM interview_roles WHERE interview_id = ANY(:ids)'
                    ), {'ids': interview_ids})
                    db.session.execute(text(
                        'DELETE FROM interview_questions WHERE interview_id = ANY(:ids)'
                    ), {'ids': interview_ids})
                    db.session.execute(text(
                        'DELETE FROM interviews WHERE id = ANY(:ids)'
                    ), {'ids': interview_ids})

                db.session.execute(text('DELETE FROM document_reviews WHERE test_procedure_id = ANY(:ids)'), {'ids': ts_ids})
                db.session.execute(text('DELETE FROM test_steps WHERE id = ANY(:ids)'), {'ids': ts_ids})

            db.session.execute(text('DELETE FROM control_evidences WHERE control_id = ANY(:ids)'), {'ids': ctrl_ids})
            db.session.execute(text('DELETE FROM control_activities WHERE id = ANY(:ids)'), {'ids': ctrl_ids})

        db.session.execute(text('DELETE FROM compliance_activities WHERE id = ANY(:ids)'), {'ids': delete_comp_ids})
        total_deleted += len(delete_comp_ids)
        print(f'Clause {clause_no}: {count} -> 6 (deleted {len(delete_comp_ids)})')

    db.session.commit()
    print(f'\nTotal deleted: {total_deleted}')
    print('Done!')
