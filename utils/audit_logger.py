
from models import db, AuditLog


def log_action(user_id, action):
    log = AuditLog(
        user_id=user_id,
        action=action
    )

    db.session.add(log)
    db.session.commit()