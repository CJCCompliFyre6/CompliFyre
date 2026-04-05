SELECT g.id, count(ca.id) as controls
FROM guidelines g
JOIN clauses c ON c.guideline_id = g.id
JOIN compliance_activities ca ON ca.clause_id = c.id
JOIN control_activities cta ON cta.compliance_activity_id = ca.id
GROUP BY g.id
LIMIT 5;