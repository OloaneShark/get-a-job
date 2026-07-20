
from datetime import datetime, timezone
from models import db, AIUsage


FREE_DAILY_LIMIT = 5
PREMIUM_DAILY_LIMIT = 25


def get_daily_ai_limit(user):
    if user.is_admin:
        return None

    if user.plan == "premium":
        return PREMIUM_DAILY_LIMIT

    return FREE_DAILY_LIMIT


def get_today_ai_usage(user_id):
    now = datetime.now(timezone.utc)

    start_of_day = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    return AIUsage.query.filter(
        AIUsage.user_id == user_id,
        AIUsage.created_at >= start_of_day
    ).count()


def can_use_ai(user):
    limit = get_daily_ai_limit(user)

    if limit is None:
        return True

    return get_today_ai_usage(user.id) < limit


def get_remaining_ai_requests(user):
    limit = get_daily_ai_limit(user)

    if limit is None:
        return None

    used = get_today_ai_usage(user.id)

    return max(limit - used, 0)


def record_ai_usage(user_id, feature):
    usage = AIUsage(
        user_id=user_id,
        feature=feature
    )

    db.session.add(usage)
    