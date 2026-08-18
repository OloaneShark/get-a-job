
import base64
import hashlib
import hmac
import io
import os
import secrets
import string
from datetime import datetime, timedelta

import pyotp
import qrcode

from models import (
    db,
    EmailVerificationCode,
    TwoFactorRecoveryCode,
)
from services.email_service import send_verification_email
from utils.encryption import encrypt_text, decrypt_text


EMAIL_CODE_TTL_MINUTES = int(
    os.getenv("EMAIL_CODE_TTL_MINUTES", "10")
)
EMAIL_CODE_RESEND_SECONDS = int(
    os.getenv("EMAIL_CODE_RESEND_SECONDS", "60")
)
EMAIL_CODE_MAX_ATTEMPTS = int(
    os.getenv("EMAIL_CODE_MAX_ATTEMPTS", "5")
)


class VerificationCooldown(Exception):
    def __init__(self, seconds_remaining):
        self.seconds_remaining = max(1, int(seconds_remaining))
        super().__init__(
            f"Wait {self.seconds_remaining} seconds."
        )


def _pepper():
    secret = os.getenv("SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "SECRET_KEY is required for verification-code hashing."
        )
    return secret.encode("utf-8")


def _hmac_hash(namespace, user_id, value):
    message = f"{namespace}:{user_id}:{value}".encode("utf-8")
    return hmac.new(
        _pepper(),
        message,
        hashlib.sha256
    ).hexdigest()


def issue_email_verification(user, force=False):
    now = datetime.utcnow()

    latest = (
        EmailVerificationCode.query
        .filter_by(user_id=user.id, consumed_at=None)
        .order_by(EmailVerificationCode.created_at.desc())
        .first()
    )

    if latest and not force and latest.created_at:
        age = (now - latest.created_at).total_seconds()
        if age < EMAIL_CODE_RESEND_SECONDS:
            raise VerificationCooldown(
                EMAIL_CODE_RESEND_SECONDS - age
            )

    for active_code in (
        EmailVerificationCode.query
        .filter_by(user_id=user.id, consumed_at=None)
        .all()
    ):
        active_code.consumed_at = now

    code = f"{secrets.randbelow(1_000_000):06d}"

    challenge = EmailVerificationCode(
        user_id=user.id,
        code_hash=_hmac_hash(
            "email-verification",
            user.id,
            code
        ),
        attempts=0,
        created_at=now,
        expires_at=now + timedelta(minutes=EMAIL_CODE_TTL_MINUTES)
    )

    db.session.add(challenge)
    db.session.flush()

    send_verification_email(user.email, code)


def verify_email_code(user, submitted_code):
    code = str(submitted_code or "").strip()
    now = datetime.utcnow()

    challenge = (
        EmailVerificationCode.query
        .filter_by(user_id=user.id, consumed_at=None)
        .order_by(EmailVerificationCode.created_at.desc())
        .first()
    )

    if challenge is None:
        return False, "No active verification code. Request a new code."

    if challenge.expires_at <= now:
        challenge.consumed_at = now
        return False, "That verification code expired. Request a new code."

    if challenge.attempts >= EMAIL_CODE_MAX_ATTEMPTS:
        challenge.consumed_at = now
        return False, "Too many incorrect attempts. Request a new code."

    expected_hash = _hmac_hash(
        "email-verification",
        user.id,
        code
    )

    if not hmac.compare_digest(challenge.code_hash, expected_hash):
        challenge.attempts += 1
        if challenge.attempts >= EMAIL_CODE_MAX_ATTEMPTS:
            challenge.consumed_at = now
        return False, "That verification code is not valid."

    challenge.consumed_at = now
    user.email_verified = True
    return True, "Email verified successfully."


def generate_totp_secret():
    return pyotp.random_base32()


def build_totp_setup(user, secret):
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=user.email,
        issuer_name="JobFinitum"
    )

    qr = qrcode.QRCode(
        version=None,
        box_size=8,
        border=4
    )
    qr.add_data(uri)
    qr.make(fit=True)
    image = qr.make_image()

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    qr_data_uri = (
        "data:image/png;base64,"
        + base64.b64encode(buffer.getvalue()).decode("ascii")
    )

    return uri, qr_data_uri


def verify_totp_secret(secret, submitted_code):
    code = str(submitted_code or "").strip().replace(" ", "")
    if not (len(code) == 6 and code.isdigit()):
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def verify_user_totp(user, submitted_code):
    if not (user.two_factor_enabled and user.totp_secret):
        return False
    try:
        secret = decrypt_text(user.totp_secret)
    except Exception:
        return False
    return verify_totp_secret(secret, submitted_code)


def enable_user_totp(user, secret):
    user.totp_secret = encrypt_text(secret)
    user.pending_totp_secret = None
    user.two_factor_enabled = True


def disable_user_totp(user):
    user.totp_secret = None
    user.pending_totp_secret = None
    user.two_factor_enabled = False
    TwoFactorRecoveryCode.query.filter_by(user_id=user.id).delete(
        synchronize_session=False
    )


def _new_recovery_code():
    alphabet = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(alphabet) for _ in range(16))
    return "-".join((raw[0:4], raw[4:8], raw[8:12], raw[12:16]))


def _recovery_hash(user_id, code):
    normalized = str(code or "").strip().upper().replace(" ", "")
    return _hmac_hash("2fa-recovery", user_id, normalized)


def replace_recovery_codes(user):
    TwoFactorRecoveryCode.query.filter_by(user_id=user.id).delete(
        synchronize_session=False
    )

    raw_codes = []
    for _ in range(8):
        code = _new_recovery_code()
        raw_codes.append(code)
        db.session.add(
            TwoFactorRecoveryCode(
                user_id=user.id,
                code_hash=_recovery_hash(user.id, code)
            )
        )
    return raw_codes


def consume_recovery_code(user, submitted_code):
    expected = _recovery_hash(user.id, submitted_code)

    for recovery_code in (
        TwoFactorRecoveryCode.query
        .filter_by(user_id=user.id, used_at=None)
        .all()
    ):
        if hmac.compare_digest(recovery_code.code_hash, expected):
            recovery_code.used_at = datetime.utcnow()
            return True
    return False
