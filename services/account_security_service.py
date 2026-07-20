
from flask import request

from models import db, AccountSecurityEvent
from utils.security_utils import hash_security_value


def get_client_ip():
    return request.remote_addr


def build_device_value():
    user_agent = request.headers.get("User-Agent", "")
    accept_language = request.headers.get("Accept-Language", "")

    return f"{user_agent}|{accept_language}"


def record_security_event(user_id, event_type):
    user_agent = request.headers.get("User-Agent", "")
    device_value = build_device_value()

    event = AccountSecurityEvent(
        user_id=user_id,
        event_type=event_type,
        ip_hash=hash_security_value(get_client_ip()),
        user_agent_hash=hash_security_value(user_agent),
        device_hash=hash_security_value(device_value)
    )

    db.session.add(event)
    