
#Implemented AI on July 2nd, 2026 at 8:27 pm est
#THIS WAS A HEADACHE TO GET WORKING
#Implemented feature for failing AI connection for AI features on July 5th, 2026
#THIS TOOK ME 2 DAYS TO GET WORKING PROPERLY WITHOUT MESSING UP AAAAAHHHHHHH
#July 25, 2026 at 10:12 pm, I HATE TRYING TO GET THESE JOB BOARDS TO WORKS BECAUSE
#ASHBY AND LEVER AND GREENHOUSE ARE ANNOYING AND I HAVE TO PULL THEIR COMPANIES MANUALLY
#AAAAAAAAAAHHHHHHHHHHHHHH I HATE IT I HATE IT I HATE IT
#WHY CANT THEY BE NICE AND SIMPLE AND CLEAN LIKE REMOTE OK???
#August 17, 2026 IT IS ALIVE MY EXPERIMENT IS ALIVE!

import os
import bcrypt
import json
import csv
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from io import StringIO
from werkzeug.utils import secure_filename
from authlib.integrations.flask_client import OAuth
from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    Response,
    send_from_directory,
    jsonify,
    session,
)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from services.resume_service import analyze_resume_text
from services.resume_text_service import extract_resume_text
from models import (
    db,
    User,
    JobApplication,
    AuditLog,
    Resume,
    InterviewPrep,
    ApplicationHistory,
    SavedJobDescription,
    AIReport,
    CompanyIntelligence,
    AIUsage,
    AccountSecurityEvent,
    DiscoveredJob,
    ApplicationPackage,
    JobSearchProfile,
    JobSourceCompany,
    JobSourceCandidate,
    CachedSourceJob,
    AutoApplyCandidate,
    ApplicantProfile,
    ApplicationSubmissionAttempt
)
from utils.encryption import encrypt_text, decrypt_text
from services.legitimacy_service import calculate_legitimacy_score
from utils.audit_logger import log_action
from services.interview_service import generate_interview_prep
from openai import RateLimitError
from forms import (
    RegistrationForm,
    LoginForm,
    JobApplicationForm,
    ResumeUploadForm,
    ResumeAnalysisForm,
    InterviewPrepForm,
    CompanyLookupForm,
    JobMatchForm,
    SavedJobDescriptionForm,
    AIResumeReviewForm,
    AICoverLetterForm,
    AIInterviewCoachForm,
    JobUrlImportForm,
    JobSearchProfileForm,
    JobSourceCompanyForm,
    JobSourceDiscoveryForm,
    EmailVerificationForm,
    ResendVerificationForm,
    ProfileSettingsForm,
    ChangePasswordForm,
    TwoFactorSetupForm,
    TwoFactorChallengeForm,
    DisableTwoFactorForm,
    DeleteAccountForm,
    ApplicantProfileForm
)
from services.company_service import analyze_company
from services.job_match_service import analyze_resume_job_match
from services.ai_resume_service import analyze_resume
from services.ai_cover_letter_service import generate_cover_letter
from services.ai_interview_services import generate_interview_coach
from services.job_url_service import extract_job_from_url
from services.manual_prompt_service import (
    build_resume_review_prompt,
    build_cover_letter_prompt,
    build_interview_coach_prompt
)
from services.ai_application_intelligence import (generate_application_intelligence)
from services.ai_usage_service import (
    can_use_ai,
    get_remaining_ai_requests,
    record_ai_usage,
    get_daily_ai_limit
)
from services.account_security_service import (
    get_client_ip,
    record_security_event
)
from services.account_auth_service import (
    VerificationCooldown,
    issue_email_verification,
    verify_email_code,
    generate_totp_secret,
    build_totp_setup,
    verify_totp_secret,
    verify_user_totp,
    enable_user_totp,
    disable_user_totp,
    replace_recovery_codes,
    consume_recovery_code
)
from services.profile_service import (
    save_profile_picture,
    delete_profile_picture
)
from services.account_delete_service import (
    delete_user_account
)
from services.scheduler_service import (
    get_automatic_source_discovery_status,
    queue_automatic_source_discovery,
    start_scheduler,
)
from services.job_sources.source_utils import (
    extract_ashby_job_board_name,
    extract_greenhouse_board_token,
    extract_lever_company_slug
)
from services.job_sources.utils import (
    build_job_fingerprint,
)
from services.job_sources.workday_crawler import (
    WorkdayCrawler,
)
from services.job_sources.discovery.source_discovery import (detect_source_type)
from services.job_sources.discovery.validation_service import (validate_source_candidate)
from services.job_sources.discovery.candidate_service import (ingest_source_urls)
from services.job_sources.discovery.common_crawl_discovery import (run_common_crawl_discovery)
from services.location_service import (
    LocationDataUnavailable,
    get_countries,
    get_states,
    get_cities,
)
from services.auto_apply_service import (
    get_auto_apply_access,
    stage_existing_auto_apply_matches,
)
from services.auto_apply_submission.engine import (
    execute_candidate_submission,
)
from services.phone_service import (
    country_region_from_name,
    get_phone_country_choices,
    normalize_phone_number,
    split_phone_for_form,
)

load_dotenv()


app = Flask(__name__)
csrf = CSRFProtect(app)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "dev-secret-key"
)

app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL"
)

app.config["GOOGLE_CLIENT_ID"] = os.getenv(
    "GOOGLE_CLIENT_ID"
)

app.config["GOOGLE_CLIENT_SECRET"] = os.getenv(
    "GOOGLE_CLIENT_SECRET"
)

app.config["GOOGLE_REDIRECT_URI"] = os.getenv(
    "GOOGLE_REDIRECT_URI"
)

app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "pool_size": 3,
    "max_overflow": 2,
}

app.config["UPLOAD_FOLDER"] = os.path.join(
    app.root_path,
    "uploads",
)

# A fresh clone/container may not have the upload directory yet.
os.makedirs(
    app.config["UPLOAD_FOLDER"],
    exist_ok=True,
)


if not app.config["SQLALCHEMY_DATABASE_URI"]:
    raise RuntimeError(
        "DATABASE_URL is not set."
    )

oauth = OAuth(app)

oauth.register(
    name="google",
    server_metadata_url=(
        "https://accounts.google.com/"
        ".well-known/openid-configuration"
    ),
    client_kwargs={
        "scope": "openid profile email"
    }
)


db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


def get_latest_resume_for_user(user_id):
    return(
        Resume.query
        .filter_by(user_id=user_id)
        .order_by(Resume.uploaded_at.desc())
        .first()
    )


def configure_search_profile_auto_apply_form(form, user_id):
    resumes = (
        Resume.query
        .filter_by(user_id=user_id)
        .order_by(Resume.uploaded_at.desc())
        .all()
    )
    form.auto_apply_resume_id.choices = [(0, "Select a resume")] + [
        (
            resume.id,
            (resume.version_name or resume.original_filename)
            + (
                f" — {resume.original_filename}"
                if resume.version_name and resume.version_name != resume.original_filename
                else ""
            ),
        )
        for resume in resumes
    ]


def canonical_job_posting_url(value):
    return (
        str(value or "")
        .strip()
        .rstrip("/")
    )


def discovered_job_action_response(
    job,
    action,
    message,
):
    # JavaScript requests get JSON so the page does
    # not have to reload over one button click.
    if request.headers.get(
        "X-Requested-With"
    ) == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "job_id": job.id,
            "action": action,
            "is_saved": job.is_saved,
            "is_ignored": job.is_ignored,
            "message": message,
        })

    flash(
        message,
        "success"
        if action in {
            "save",
            "restore",
        }
        else "info",
    )

    return redirect(
        request.referrer
        or url_for(
            "discovered_jobs"
        )
    )


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.context_processor
def inject_ai_usage():
    if not current_user.is_authenticated:
        return {
            "ai_daily_limit": None,
            "ai_requests_remaining": None,
            "ai_usage_unlimited": False,
            "user_plan": None
        }

    daily_limit = get_daily_ai_limit(current_user)
    remaining = get_remaining_ai_requests(current_user)

    user_plan = (
        "Admin"
        if current_user.is_admin
        else current_user.plan.title()
    )

    return {
        "ai_daily_limit": daily_limit,
        "ai_requests_remaining": remaining,
        "ai_usage_unlimited": daily_limit is None,
        "user_plan": user_plan
    }


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = RegistrationForm()

    if form.validate_on_submit():
        username = form.username.data.strip()
        email = form.email.data.strip().lower()

        if (
            User.query
            .filter(db.func.lower(User.username) == username.lower())
            .first()
        ):
            flash("That username is already in use.", "danger")
            return render_template("register.html", form=form)

        if (
            User.query
            .filter(db.func.lower(User.email) == email)
            .first()
        ):
            flash("An account with that email already exists.", "danger")
            return render_template("register.html", form=form)

        hashed_password = bcrypt.hashpw(
            form.password.data.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        user = User(
            username=username,
            email=email,
            password=hashed_password,
            email_verified=False,
            last_ip=get_client_ip()
        )

        try:
            db.session.add(user)
            db.session.flush()
            record_security_event(user.id, "registration")
            issue_email_verification(user, force=True)
            db.session.commit()

            session["pending_email_verification_user_id"] = user.id

            flash(
                "Account created. We sent a 6-digit verification "
                "code to your email.",
                "success"
            )
            return redirect(url_for("verify_email"))

        except Exception as error:
            db.session.rollback()
            print("REGISTRATION ERROR:", repr(error))
            flash(
                "The account could not be created. Please try again.",
                "danger"
            )

    return render_template("register.html", form=form)


def generate_google_username(email):
    email_prefix = email.split("@", 1)[0]

    base = "".join(
        character
        for character in email_prefix
        if character.isalnum()
        or character == "_"
    )

    if not base:
        base = "google_user"

    base = base[:70]

    candidate = base
    counter = 1

    while User.query.filter_by(
        username=candidate
    ).first():
        suffix = f"_{counter}"

        candidate = (
            base[:80 - len(suffix)]
            + suffix
        )

        counter += 1

    return candidate


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = LoginForm()

    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = (
            User.query
            .filter(db.func.lower(User.email) == email)
            .first()
        )

        if (
            user
            and user.password
            and bcrypt.checkpw(
                form.password.data.encode("utf-8"),
                user.password.encode("utf-8")
            )
        ):
            if not user.email_verified:
                session["pending_email_verification_user_id"] = user.id

                try:
                    issue_email_verification(user)
                    db.session.commit()
                    flash(
                        "Verify your email before logging in. "
                        "We sent you a new verification code.",
                        "warning"
                    )
                except VerificationCooldown:
                    db.session.rollback()
                    flash(
                        "Verify your email before logging in. "
                        "Use the code we already sent you.",
                        "warning"
                    )
                except Exception as error:
                    db.session.rollback()
                    print("EMAIL VERIFICATION SEND ERROR:", repr(error))
                    flash(
                        "Your email is not verified, and a new code "
                        "could not be sent right now.",
                        "danger"
                    )

                return redirect(url_for("verify_email"))

            return start_user_login(
                user,
                "login",
                "User logged in"
            )

        flash(
            "Login failed. Check your email and password again.",
            "danger"
        )

    return render_template("login.html", form=form)


@app.route("/auth/google")
def google_login():
    if current_user.is_authenticated:
        return redirect(
            url_for("dashboard")
        )

    redirect_uri = app.config.get(
        "GOOGLE_REDIRECT_URI"
    )

    if not (
        app.config.get("GOOGLE_CLIENT_ID")
        and app.config.get(
            "GOOGLE_CLIENT_SECRET"
        )
        and redirect_uri
    ):
        flash(
            "Google sign-in is not configured.",
            "danger"
        )

        return redirect(
            url_for("login")
        )

    return oauth.google.authorize_redirect(
        redirect_uri
    )


@app.route("/auth/google/callback")
def google_callback():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    try:
        token = oauth.google.authorize_access_token()
        userinfo = token.get("userinfo")
    except Exception as error:
        print("GOOGLE OAUTH ERROR:", repr(error))
        flash(
            "Google sign-in could not be completed. Please try again.",
            "danger"
        )
        return redirect(url_for("login"))

    if not userinfo:
        flash("Google did not return account information.", "danger")
        return redirect(url_for("login"))

    google_sub = str(userinfo.get("sub", "")).strip()
    email = str(userinfo.get("email", "")).strip().lower()
    email_verified = (
        userinfo.get("email_verified") is True
        or str(userinfo.get("email_verified", "")).lower() == "true"
    )

    if not google_sub or not email or not email_verified:
        flash("Google could not verify this account.", "danger")
        return redirect(url_for("login"))

    user = User.query.filter_by(google_sub=google_sub).first()

    try:
        if user is None:
            existing_email_user = (
                User.query
                .filter(db.func.lower(User.email) == email)
                .first()
            )

            if existing_email_user:
                flash(
                    "An account with that email already exists. "
                    "Log in with your password first.",
                    "warning"
                )
                return redirect(url_for("login"))

            user = User(
                username=generate_google_username(email),
                email=email,
                password=None,
                google_sub=google_sub,
                email_verified=True,
                last_ip=get_client_ip()
            )
            db.session.add(user)
            db.session.flush()
            record_security_event(user.id, "registration_google")
        else:
            user.email_verified = True

        db.session.commit()

        return start_user_login(
            user,
            "login_google",
            "User logged in with Google"
        )

    except Exception as error:
        db.session.rollback()
        print("GOOGLE LOGIN DATABASE ERROR:", repr(error))
        flash(
            "Google sign-in could not be completed. Please try again.",
            "danger"
        )
        return redirect(url_for("login"))


def finish_user_login(user, security_event, audit_message):
    try:
        user.last_ip = get_client_ip()
        record_security_event(user.id, security_event)
        db.session.commit()

        login_user(user)
        log_action(user.id, audit_message)
        flash("Login successful.", "success")
        return redirect(url_for("dashboard"))
    except Exception as error:
        db.session.rollback()
        print("LOGIN COMPLETION ERROR:", repr(error))
        flash("Login could not be completed. Please try again.", "danger")
        return redirect(url_for("login"))


def start_user_login(user, security_event, audit_message):
    if user.two_factor_enabled:
        session["pending_2fa_user_id"] = user.id
        session["pending_2fa_security_event"] = security_event
        session["pending_2fa_audit_message"] = audit_message
        session["pending_2fa_expires_at"] = time.time() + 600
        session["pending_2fa_attempts"] = 0
        return redirect(url_for("two_factor_challenge"))

    return finish_user_login(user, security_event, audit_message)


@app.route("/verify-email", methods=["GET", "POST"])
def verify_email():
    user_id = session.get("pending_email_verification_user_id")
    if not user_id:
        flash(
            "Start from registration or login to verify an email address.",
            "warning"
        )
        return redirect(url_for("login"))

    user = db.session.get(User, int(user_id))
    if user is None:
        session.pop("pending_email_verification_user_id", None)
        return redirect(url_for("register"))

    if user.email_verified:
        session.pop("pending_email_verification_user_id", None)
        flash("Your email is already verified.", "info")
        return redirect(url_for("login"))

    form = EmailVerificationForm()
    resend_form = ResendVerificationForm()

    if form.validate_on_submit():
        ok, message = verify_email_code(user, form.code.data)
        if ok:
            record_security_event(user.id, "email_verified")
            db.session.commit()
            session.pop("pending_email_verification_user_id", None)
            flash(message + " You can now log in.", "success")
            return redirect(url_for("login"))

        db.session.commit()
        flash(message, "danger")

    return render_template(
        "verify_email.html",
        form=form,
        resend_form=resend_form,
        email=user.email
    )


@app.route("/verify-email/resend", methods=["POST"])
def resend_verification_email():
    form = ResendVerificationForm()
    if not form.validate_on_submit():
        return redirect(url_for("verify_email"))

    user_id = session.get("pending_email_verification_user_id")
    user = db.session.get(User, int(user_id)) if user_id else None

    if user is None:
        flash("There is no email waiting for verification.", "warning")
        return redirect(url_for("login"))
    if user.email_verified:
        return redirect(url_for("login"))

    try:
        issue_email_verification(user)
        db.session.commit()
        flash("A new verification code was sent.", "success")
    except VerificationCooldown as error:
        db.session.rollback()
        flash(
            f"Wait {error.seconds_remaining} seconds before requesting "
            "another code.",
            "warning"
        )
    except Exception as error:
        db.session.rollback()
        print("VERIFICATION RESEND ERROR:", repr(error))
        flash("A new verification code could not be sent.", "danger")

    return redirect(url_for("verify_email"))


@app.route("/auth/2fa", methods=["GET", "POST"])
def two_factor_challenge():
    user_id = session.get("pending_2fa_user_id")
    expires_at = session.get("pending_2fa_expires_at", 0)

    if not user_id or time.time() > expires_at:
        session.pop("pending_2fa_user_id", None)
        flash(
            "Your two-step login session expired. Log in again.",
            "warning"
        )
        return redirect(url_for("login"))

    user = db.session.get(User, int(user_id))
    if user is None:
        return redirect(url_for("login"))

    form = TwoFactorChallengeForm()

    if form.validate_on_submit():
        submitted = form.code.data.strip()
        valid = verify_user_totp(user, submitted)
        used_recovery = False

        if not valid:
            used_recovery = consume_recovery_code(user, submitted)
            valid = used_recovery

        if valid:
            security_event = session.pop(
                "pending_2fa_security_event",
                "login_2fa"
            )
            audit_message = session.pop(
                "pending_2fa_audit_message",
                "User logged in with two-step verification"
            )
            session.pop("pending_2fa_user_id", None)
            session.pop("pending_2fa_expires_at", None)
            session.pop("pending_2fa_attempts", None)

            if used_recovery:
                record_security_event(user.id, "recovery_code_used")

            return finish_user_login(user, security_event, audit_message)

        attempts = session.get("pending_2fa_attempts", 0) + 1
        session["pending_2fa_attempts"] = attempts

        if attempts >= 8:
            session.pop("pending_2fa_user_id", None)
            flash("Too many incorrect codes. Log in again.", "danger")
            return redirect(url_for("login"))

        flash(
            "That authenticator or recovery code is not valid.",
            "danger"
        )

    return render_template("two_factor_challenge.html", form=form)


@app.route("/settings")
@login_required
def settings():
    profile_form = ProfileSettingsForm()
    profile_form.username.data = current_user.username

    return render_template(
        "settings.html",
        profile_form=profile_form,
        password_form=ChangePasswordForm(),
        disable_2fa_form=DisableTwoFactorForm(),
        delete_form=DeleteAccountForm()
    )


@app.route("/settings/profile", methods=["POST"])
@login_required
def update_profile_settings():
    form = ProfileSettingsForm()

    if not form.validate_on_submit():
        for errors in form.errors.values():
            for error in errors:
                flash(error, "danger")
        return redirect(url_for("settings"))

    username = form.username.data.strip()
    existing_user = (
        User.query
        .filter(
            db.func.lower(User.username) == username.lower(),
            User.id != current_user.id
        )
        .first()
    )

    if existing_user:
        flash("That username is already in use.", "danger")
        return redirect(url_for("settings"))

    current_user.username = username
    upload = form.profile_picture.data

    if upload and getattr(upload, "filename", ""):
        try:
            old_filename = current_user.profile_image
            new_filename = save_profile_picture(upload, current_user.id)
            current_user.profile_image = new_filename
            if old_filename and old_filename != new_filename:
                delete_profile_picture(old_filename)
        except ValueError as error:
            flash(str(error), "danger")
            return redirect(url_for("settings"))

    db.session.commit()
    log_action(current_user.id, "Updated account profile")
    flash("Profile updated.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/password", methods=["POST"])
@login_required
def update_password_settings():
    form = ChangePasswordForm()

    if not form.validate_on_submit():
        for errors in form.errors.values():
            for error in errors:
                flash(error, "danger")
        return redirect(url_for("settings"))

    if current_user.password:
        if not form.current_password.data:
            flash("Enter your current password.", "danger")
            return redirect(url_for("settings"))

        if not bcrypt.checkpw(
            form.current_password.data.encode("utf-8"),
            current_user.password.encode("utf-8")
        ):
            flash("Your current password is incorrect.", "danger")
            return redirect(url_for("settings"))

    current_user.password = bcrypt.hashpw(
        form.new_password.data.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    record_security_event(current_user.id, "password_changed")
    db.session.commit()
    flash("Password updated.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/2fa/setup", methods=["GET", "POST"])
@login_required
def setup_two_factor():
    if current_user.two_factor_enabled:
        flash("Two-step verification is already enabled.", "info")
        return redirect(url_for("settings"))

    if not current_user.pending_totp_secret:
        secret = generate_totp_secret()
        current_user.pending_totp_secret = encrypt_text(secret)
        db.session.commit()
    else:
        secret = decrypt_text(current_user.pending_totp_secret)

    _, qr_data_uri = build_totp_setup(current_user, secret)
    form = TwoFactorSetupForm()

    if form.validate_on_submit():
        if not verify_totp_secret(secret, form.code.data):
            flash("That authenticator code is not valid.", "danger")
            return render_template(
                "two_factor_setup.html",
                form=form,
                secret=secret,
                qr_data_uri=qr_data_uri
            )

        enable_user_totp(current_user, secret)
        recovery_codes = replace_recovery_codes(current_user)
        record_security_event(current_user.id, "two_factor_enabled")
        db.session.commit()

        return render_template(
            "recovery_codes.html",
            recovery_codes=recovery_codes
        )

    return render_template(
        "two_factor_setup.html",
        form=form,
        secret=secret,
        qr_data_uri=qr_data_uri
    )


@app.route("/settings/2fa/disable", methods=["POST"])
@login_required
def disable_two_factor_settings():
    form = DisableTwoFactorForm()

    if not form.validate_on_submit():
        flash("Enter a valid verification code.", "danger")
        return redirect(url_for("settings"))

    if current_user.password:
        if not (
            form.password.data
            and bcrypt.checkpw(
                form.password.data.encode("utf-8"),
                current_user.password.encode("utf-8")
            )
        ):
            flash(
                "Your password is required to disable two-step verification.",
                "danger"
            )
            return redirect(url_for("settings"))

    code = form.code.data.strip()
    valid = verify_user_totp(current_user, code)
    if not valid:
        valid = consume_recovery_code(current_user, code)

    if not valid:
        flash(
            "That authenticator or recovery code is not valid.",
            "danger"
        )
        return redirect(url_for("settings"))

    disable_user_totp(current_user)
    record_security_event(current_user.id, "two_factor_disabled")
    db.session.commit()

    flash("Two-step verification disabled.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/delete", methods=["POST"])
@login_required
def delete_account_settings():
    form = DeleteAccountForm()

    if not form.validate_on_submit():
        flash(
            'Type "DELETE" and complete the required security fields.',
            "danger"
        )
        return redirect(url_for("settings"))

    if form.confirmation.data.strip().upper() != "DELETE":
        flash('Type "DELETE" exactly to confirm account deletion.', "danger")
        return redirect(url_for("settings"))

    if current_user.password:
        if not (
            form.password.data
            and bcrypt.checkpw(
                form.password.data.encode("utf-8"),
                current_user.password.encode("utf-8")
            )
        ):
            flash("Your password is required to delete your account.", "danger")
            return redirect(url_for("settings"))

    if current_user.two_factor_enabled:
        submitted_2fa = (form.two_factor_code.data or "").strip()
        valid_2fa = verify_user_totp(current_user, submitted_2fa)
        if not valid_2fa:
            valid_2fa = consume_recovery_code(current_user, submitted_2fa)
        if not valid_2fa:
            flash(
                "A valid two-step verification code is required to "
                "delete your account.",
                "danger"
            )
            return redirect(url_for("settings"))

    user = current_user._get_current_object()
    profile_image = user.profile_image

    try:
        delete_user_account(user)
        db.session.commit()
        delete_profile_picture(profile_image)
        logout_user()
        session.clear()

        flash(
            "Your JobFinitum account and stored account data were deleted.",
            "success"
        )
        return redirect(url_for("home"))

    except Exception as error:
        db.session.rollback()
        print("ACCOUNT DELETE ERROR:", repr(error))
        flash(
            "Your account could not be deleted. Nothing was changed.",
            "danger"
        )
        return redirect(url_for("settings"))


@app.route("/logout")
@login_required
def logout():
    logout_user()

    for key in (
        "pending_2fa_user_id",
        "pending_2fa_security_event",
        "pending_2fa_audit_message",
        "pending_2fa_expires_at",
        "pending_2fa_attempts",
        "pending_email_verification_user_id",
    ):
        session.pop(key, None)

    flash("You have been logged out.", "info")
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():

    applications_query = JobApplication.query.filter_by(
        user_id=current_user.id
    )

    search = request.args.get("search")

    if search:
        applications_query = applications_query.filter(
            JobApplication.company_name.ilike(f"%{search}%")
        )

    status = request.args.get("status")

    if status:
        applications_query = applications_query.filter_by(
            status=status
        )

    visa = request.args.get("visa")

    if visa == "yes":
        applications_query = applications_query.filter_by(
            visa_sponsorship=True
        )

    elif visa == "no":
        applications_query = applications_query.filter_by(
            visa_sponsorship=False
        )

    filtered_applications = applications_query.all()

    return render_template(
        "dashboard.html",
        filtered_applications=filtered_applications
    )


@app.route("/admin")
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash("Administrator access is required.", "danger")
        return redirect(url_for("dashboard"))

    active_sources = JobSourceCompany.query.filter_by(is_active=True).count()
    disabled_sources = JobSourceCompany.query.filter_by(is_active=False).count()

    pending_candidates = JobSourceCandidate.query.filter_by(
        validation_status="pending"
    ).count()

    valid_candidates = JobSourceCandidate.query.filter_by(
        validation_status="valid"
    ).count()

    invalid_candidates = JobSourceCandidate.query.filter_by(
        validation_status="invalid"
    ).count()

    approved_candidates = JobSourceCandidate.query.filter_by(
        validation_status="approved"
    ).count()

    failed_sources = JobSourceCompany.query.filter_by(
        last_check_status="Failed"
    ).count()

    discovered_jobs_count = DiscoveredJob.query.count()

    recent_candidates = (
        JobSourceCandidate.query
        .order_by(JobSourceCandidate.discovered_at.desc())
        .limit(10)
        .all()
    )

    recent_sources = (
        JobSourceCompany.query
        .order_by(JobSourceCompany.created_at.desc())
        .limit(10)
        .all()
    )

    return render_template(
        "admin_dashboard.html",
        active_sources=active_sources,
        disabled_sources=disabled_sources,
        pending_candidates=pending_candidates,
        valid_candidates=valid_candidates,
        invalid_candidates=invalid_candidates,
        approved_candidates=approved_candidates,
        failed_sources=failed_sources,
        discovered_jobs_count=discovered_jobs_count,
        recent_candidates=recent_candidates,
        recent_sources=recent_sources
    )


@app.route("/admin/job-sources")
@login_required
def job_sources():
    if not current_user.is_admin:
        flash("Administrator access is required.", "danger")
        return redirect(url_for("dashboard"))

    sources = JobSourceCompany.query.order_by(
        JobSourceCompany.company_name.asc()
    ).all()

    return render_template(
        "job_sources.html",
        sources=sources
    )


@app.route("/admin/job-sources/<int:source_id>/toggle", methods=["POST"])
@login_required
def toggle_job_source(source_id):
    if not current_user.is_admin:
        flash("Administrator access is required.", "danger")
        return redirect(url_for("dashboard"))

    source = db.session.get(
        JobSourceCompany,
        source_id
    )

    if source is None:
        flash("Job source not found.", "warning")
        return redirect(url_for("job_sources"))

    try:
        source.is_active = not source.is_active
        db.session.commit()

        state = "enabled" if source.is_active else "disabled"

        flash(
            f"{source.company_name} was {state}.",
            "success"
        )

    except Exception as error:
        db.session.rollback()
        print("JOB SOURCE TOGGLE ERROR:", repr(error))
        flash(
            "The job source status could not be changed.",
            "danger"
        )

    return redirect(url_for("job_sources"))


@app.route("/admin/job-sources/<int:source_id>/delete", methods=["POST"])
@login_required
def delete_job_source(source_id):
    if not current_user.is_admin:
        flash("Administrator access is required.", "danger")
        return redirect(url_for("dashboard"))

    source = db.session.get(
        JobSourceCompany,
        source_id
    )

    if source is None:
        flash("Job source not found.", "warning")
        return redirect(url_for("job_sources"))

    company_name = source.company_name

    try:
        db.session.delete(source)
        db.session.commit()

        flash(
            f"{company_name} job source was deleted.",
            "success"
        )

    except Exception as error:
        db.session.rollback()
        print("JOB SOURCE DELETE ERROR:", repr(error))
        flash(
            "The job source could not be deleted.",
            "danger"
        )

    return redirect(url_for("job_sources"))


@app.route("/admin/job-sources/new", methods=["GET", "POST"])
@login_required
def new_job_source():
    if not current_user.is_admin:
        flash("Administrator access is required.", "danger")
        return redirect(url_for("dashboard"))

    form = JobSourceCompanyForm()

    if form.validate_on_submit():
        try:
            source_identifier = form.source_identifier.data.strip()

            if form.source_type.data == "greenhouse":
                source_identifier = extract_greenhouse_board_token(
                    source_identifier
                )

            elif form.source_type.data == "lever":
                source_identifier = extract_lever_company_slug(
                    source_identifier
                )
                
            elif form.source_type.data == "ashby":
                source_identifier = extract_ashby_job_board_name(
                    source_identifier
                )

            elif form.source_type.data == "workday":
                source_identifier = WorkdayCrawler.canonical_board_url(
                    source_identifier
                )

            existing_source = JobSourceCompany.query.filter_by(
                source_type=form.source_type.data,
                source_identifier=source_identifier
            ).first()

            if existing_source:
                flash("That job source is already configured.", "warning")
                return render_template(
                    "job_source_form.html",
                    form=form
                )

            source = JobSourceCompany(
                company_name=form.company_name.data.strip(),
                source_type=form.source_type.data,
                source_identifier=source_identifier,
                careers_url=(
                    form.careers_url.data.strip()
                    if form.careers_url.data
                    else None
                ),
                is_active=form.is_active.data
            )

            db.session.add(source)
            db.session.commit()

            flash("Job source added successfully.", "success")
            return redirect(url_for("job_sources"))

        except ValueError as error:
            db.session.rollback()
            flash(str(error), "warning")

        except Exception as error:
            db.session.rollback()
            print("JOB SOURCE CREATION ERROR:", repr(error))
            flash("The job source could not be saved.", "danger")

    return render_template(
        "job_source_form.html",
        form=form
    )


@app.route("/admin/job-source-candidates", methods=["GET", "POST"])
@login_required
def job_source_candidates():
    if not current_user.is_admin:
        flash("Administrator access is required.", "danger")
        return redirect(url_for("dashboard"))

    form = JobSourceDiscoveryForm()

    if form.validate_on_submit():
        urls = [
            line.strip()
            for line in form.source_urls.data.splitlines()
            if line.strip()
        ]

        results = ingest_source_urls(
            urls=urls,
            discovery_method="admin_bulk_import",
            auto_validate=True,
            keep_invalid=True
        )

        flash(
            f"Discovery complete: "
            f"{results['created']} added, "
            f"{results['already_active']} already active, "
            f"{results['already_candidate']} already queued, "
            f"{results['failed']} failed.",
            "success"
        )

        return redirect(url_for("job_source_candidates"))

    selected_source = (
        request.args.get(
            "source",
            ""
        )
        .strip()
        .lower()
    )

    candidate_query = (
        JobSourceCandidate.query
        .filter(
            JobSourceCandidate.validation_status.notin_([
                "approved",
                "dismissed"
            ])
        )
    )

    source_counts = {}

    source_type_rows = (
        candidate_query
        .with_entities(
            JobSourceCandidate.source_type
        )
        .all()
    )

    for source_type_row in source_type_rows:
        source_type = str(
            source_type_row[0]
            or ""
        ).strip().lower()

        if not source_type:
            continue

        source_counts[source_type] = (
            source_counts.get(
                source_type,
                0
            )
            + 1
        )

    source_filters = sorted(
        source_counts.items(),
        key=lambda item: item[0]
    )

    candidate_total = sum(
        source_counts.values()
    )

    if (
        selected_source
        and selected_source
        not in source_counts
    ):
        selected_source = ""

    if selected_source:
        candidate_query = (
            candidate_query.filter(
                JobSourceCandidate.source_type
                == selected_source
            )
        )

    candidates = (
        candidate_query
        .order_by(
            JobSourceCandidate.discovered_at.desc()
        )
        .all()
    )

    return render_template(
        "job_source_candidates.html",
        form=form,
        candidates=candidates,
        source_filters=source_filters,
        selected_source=selected_source,
        candidate_total=candidate_total
    )


@app.route("/admin/job-source-candidates/<int:candidate_id>/approve", methods=["POST"])
@login_required
def approve_job_source_candidate(candidate_id):
    ajax_request = (
        request.headers.get("X-Requested-With")
        == "XMLHttpRequest"
    )

    if not current_user.is_admin:
        if ajax_request:
            return jsonify({
                "success": False,
                "message": "Administrator access is required.",
            }), 403

        flash("Administrator access is required.", "danger")
        return redirect(url_for("dashboard"))

    candidate = JobSourceCandidate.query.get_or_404(
        candidate_id
    )

    if candidate.validation_status != "valid":
        message = "Only validated sources can be approved."

        if ajax_request:
            return jsonify({
                "success": False,
                "message": message,
            }), 409

        flash(message, "warning")
        return redirect(
            url_for("job_source_candidates")
        )

    existing_source = JobSourceCompany.query.filter_by(
        source_type=candidate.source_type,
        source_identifier=candidate.source_identifier
    ).first()

    if existing_source:
        candidate.validation_status = "approved"
        db.session.commit()

        message = (
            "That source already exists and was marked approved."
        )
        source_id = existing_source.id
        category = "info"

    else:
        source = JobSourceCompany(
            company_name=(
                candidate.company_name
                or candidate.source_identifier
            ),
            source_type=candidate.source_type,
            source_identifier=candidate.source_identifier,
            careers_url=candidate.discovered_url,
            is_active=True
        )

        db.session.add(source)
        candidate.validation_status = "approved"
        db.session.commit()

        message = (
            f"{source.company_name} was approved and activated."
        )
        source_id = source.id
        category = "success"

    if ajax_request:
        return jsonify({
            "success": True,
            "action": "approve",
            "candidate_id": candidate.id,
            "source_id": source_id,
            "message": message,
            "category": category,
            "remove_row": True,
        })

    flash(message, category)
    return redirect(
        url_for("job_source_candidates")
    )


@app.route("/admin/job-source-candidates/approve-all-valid", methods=["POST"])
@login_required
def approve_all_valid_job_sources():
    if not current_user.is_admin:
        flash("Administrator access is required.", "danger")
        return redirect(url_for("dashboard"))

    selected_source = (
        request.form.get("source", "")
        .strip()
        .lower()
    )

    candidates_query = (
        JobSourceCandidate.query.filter_by(
            validation_status="valid"
        )
    )

    if selected_source:
        candidates_query = candidates_query.filter(
            JobSourceCandidate.source_type
            == selected_source
        )

    candidates = candidates_query.all()

    approved_count = 0
    skipped_count = 0

    for candidate in candidates:
        existing_source = JobSourceCompany.query.filter_by(
            source_type=candidate.source_type,
            source_identifier=candidate.source_identifier
        ).first()

        if existing_source:
            candidate.validation_status = "approved"
            skipped_count += 1
            continue

        source = JobSourceCompany(
            company_name=(
                candidate.company_name
                or candidate.source_identifier
            ),
            source_type=candidate.source_type,
            source_identifier=candidate.source_identifier,
            careers_url=candidate.discovered_url,
            is_active=True
        )

        db.session.add(source)
        candidate.validation_status = "approved"
        approved_count += 1

    db.session.commit()

    scope_label = (
        selected_source.replace("_", " ").title()
        if selected_source
        else "All Sources"
    )

    flash(
        f"{approved_count} sources approved for {scope_label}. "
        f"{skipped_count} already existed.",
        "success"
    )

    return redirect(
        url_for(
            "job_source_candidates",
            **(
                {"source": selected_source}
                if selected_source
                else {}
            )
        )
    )


@app.route("/admin/job-source-candidates/<int:candidate_id>/validate", methods=["POST"])
@login_required
def validate_job_source_candidate(candidate_id):
    if not current_user.is_admin:
        flash("Administrator access is required.", "danger")
        return redirect(url_for("dashboard"))

    candidate = JobSourceCandidate.query.get_or_404(
        candidate_id
    )

    valid, job_count = validate_source_candidate(
        candidate
    )

    db.session.commit()

    if valid:
        flash(
            f"Source validated successfully. "
            f"{job_count} current jobs found.",
            "success"
        )
    else:
        flash(
            f"Validation failed: "
            f"{candidate.validation_error}",
            "danger"
        )

    return redirect(
        url_for("job_source_candidates")
    )


@app.route("/admin/job-source-candidates/<int:candidate_id>/reject", methods=["POST"])
@login_required
def reject_job_source_candidate(candidate_id):
    ajax_request = (
        request.headers.get("X-Requested-With")
        == "XMLHttpRequest"
    )

    if not current_user.is_admin:
        if ajax_request:
            return jsonify({
                "success": False,
                "message": "Administrator access is required.",
            }), 403

        flash("Administrator access is required.", "danger")
        return redirect(url_for("dashboard"))

    candidate = JobSourceCandidate.query.get_or_404(
        candidate_id
    )

    candidate.validation_status = "dismissed"
    candidate.validation_error = (
        candidate.validation_error
        or "Rejected by administrator."
    )

    db.session.commit()

    message = (
        "Source rejected and blocked from future discovery."
    )

    if ajax_request:
        return jsonify({
            "success": True,
            "action": "reject",
            "candidate_id": candidate.id,
            "message": message,
            "category": "info",
            "remove_row": True,
        })

    flash(message, "info")
    return redirect(
        url_for("job_source_candidates")
    )


@app.route(
    "/admin/job-source-candidates/run-discovery",
    methods=["POST"],
)
@login_required
def run_job_source_discovery():
    ajax_request = (
        request.headers.get("X-Requested-With")
        == "XMLHttpRequest"
    )

    if not current_user.is_admin:
        message = "Administrator access is required."

        if ajax_request:
            return jsonify({
                "success": False,
                "message": message,
            }), 403

        flash(message, "danger")
        return redirect(url_for("dashboard"))

    try:
        queued, status = queue_automatic_source_discovery(
            app,
            limit_per_source=20,
        )

    except Exception as error:
        print(
            "AUTOMATIC DISCOVERY QUEUE FAILED | "
            f"Error: {error}"
        )
        message = (
            "Automatic discovery could not be started: "
            f"{error}"
        )

        if ajax_request:
            return jsonify({
                "success": False,
                "message": message,
            }), 500

        flash(message, "danger")
        return redirect(url_for("job_source_candidates"))

    if queued:
        message = (
            "Automatic discovery started in the background. "
            "This page will update when it finishes."
        )
        response_status = 202
        category = "info"
    else:
        message = (
            "Automatic discovery is already queued or running."
        )
        response_status = 200
        category = "warning"

    if ajax_request:
        return jsonify({
            "success": True,
            "queued": queued,
            "state": status.get("state"),
            "run_id": status.get("run_id"),
            "message": message,
            "category": category,
        }), response_status

    flash(message, category)
    return redirect(url_for("job_source_candidates"))


@app.route(
    "/admin/job-source-candidates/discovery-status",
    methods=["GET"],
)
@login_required
def job_source_discovery_status():
    if not current_user.is_admin:
        return jsonify({
            "success": False,
            "message": "Administrator access is required.",
        }), 403

    status = get_automatic_source_discovery_status()
    return jsonify({
        "success": True,
        **status,
    })


@app.route("/admin/job-source-candidates/cleanup-invalid", methods=["POST"])
@login_required
def cleanup_invalid_job_source_candidates():
    if not current_user.is_admin:
        flash("Administrator access is required.", "danger")
        return redirect(url_for("dashboard"))

    selected_source = (
        request.form.get("source", "")
        .strip()
        .lower()
    )

    invalid_query = (
        JobSourceCandidate.query
        .filter(
            JobSourceCandidate.validation_status.in_([
                "invalid",
                "rejected"
            ])
        )
    )

    if selected_source:
        invalid_query = invalid_query.filter(
            JobSourceCandidate.source_type
            == selected_source
        )

    invalid_candidates = invalid_query.all()
    dismissed_count = len(invalid_candidates)

    for candidate in invalid_candidates:
        candidate.validation_status = "dismissed"

    db.session.commit()

    scope_label = (
        selected_source.replace("_", " ").title()
        if selected_source
        else "All Sources"
    )

    flash(
        f"{dismissed_count} invalid candidates cleared "
        f"for {scope_label} and blocked from future discovery.",
        "success"
    )

    return redirect(
        url_for(
            "job_source_candidates",
            **(
                {"source": selected_source}
                if selected_source
                else {}
            )
        )
    )


@app.route("/admin/job-source-candidates/cleanup-approved", methods=["POST"])
@login_required
def cleanup_approved_job_source_candidates():
    if not current_user.is_admin:
        flash("Administrator access is required.", "danger")
        return redirect(url_for("dashboard"))

    selected_source = (
        request.form.get("source", "")
        .strip()
        .lower()
    )

    approved_query = (
        JobSourceCandidate.query.filter_by(
            validation_status="approved"
        )
    )

    if selected_source:
        approved_query = approved_query.filter(
            JobSourceCandidate.source_type
            == selected_source
        )

    approved_candidates = approved_query.all()
    deleted_count = len(approved_candidates)

    for candidate in approved_candidates:
        db.session.delete(candidate)

    db.session.commit()

    scope_label = (
        selected_source.replace("_", " ").title()
        if selected_source
        else "All Sources"
    )

    flash(
        f"{deleted_count} approved candidates removed "
        f"from the queue for {scope_label}.",
        "success"
    )

    return redirect(
        url_for(
            "job_source_candidates",
            **(
                {"source": selected_source}
                if selected_source
                else {}
            )
        )
    )


@app.route("/applications/new", methods=["GET", "POST"])
@login_required
def add_application():
    form = JobApplicationForm()

    if form.validate_on_submit():
        score, risk_level, red_flags = calculate_legitimacy_score(
            form.company_website.data,
            form.job_posting_url.data,
            form.recruiter_email.data,
            form.salary.data,
            form.notes.data
        )

        application = JobApplication(
            company_name=form.company_name.data,
            position_title=form.position_title.data,
            company_website=form.company_website.data,
            job_posting_url=form.job_posting_url.data,
            recruiter_email=form.recruiter_email.data,
            status=form.status.data,
            salary=form.salary.data,
            location=form.location.data,
            visa_sponsorship=form.visa_sponsorship.data,
            notes=encrypt_text(form.notes.data),
            legitimacy_score=score,
            risk_level=risk_level,
            user_id=current_user.id,
            follow_up_date=form.follow_up_date.data,
            last_contacted_date=form.last_contacted_date.data,
            job_description=form.job_description.data
        )

        db.session.add(application)
        db.session.flush()

        history_entry = ApplicationHistory(
            status=application.status,
            note="Application created",
            application_id=application.id
        )

        db.session.add(history_entry)
        db.session.commit()

        log_action(current_user.id, f"Created application for {application.company_name}")
        
        flash("Job application saved successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template("add_application.html", form=form, title="Add Application")


@app.route("/applications/<int:application_id>/edit", methods=["GET", "POST"])
@login_required
def edit_application(application_id):
    application = JobApplication.query.get_or_404(application_id)

    if application.user_id != current_user.id:
        flash("You are not authorized to edit this application.", "danger")
        return redirect(url_for("dashboard"))

    form = JobApplicationForm()

    if form.validate_on_submit():
        old_status = application.status

        score, risk_level, _ = calculate_legitimacy_score(
            form.company_website.data,
            form.job_posting_url.data,
            form.recruiter_email.data,
            form.salary.data,
            form.notes.data
        )

        application.company_name = form.company_name.data
        application.position_title = form.position_title.data
        application.company_website = form.company_website.data
        application.job_posting_url = form.job_posting_url.data
        application.job_description = form.job_description.data
        application.recruiter_email = form.recruiter_email.data
        application.status = form.status.data
        application.salary = form.salary.data
        application.location = form.location.data
        application.visa_sponsorship = form.visa_sponsorship.data
        application.notes = encrypt_text(form.notes.data)
        application.legitimacy_score = score
        application.risk_level = risk_level
        application.follow_up_date = form.follow_up_date.data
        application.last_contacted_date = form.last_contacted_date.data

        if old_status != form.status.data:
            history_entry = ApplicationHistory(
                status=form.status.data,
                note=f"Status changed from {old_status} to {form.status.data}",
                application_id=application.id
            )

            db.session.add(history_entry)

        db.session.commit()
        
        log_action(current_user.id, f"Updated application for {application.company_name}")

        flash("Application updated successfully.", "success")
        return redirect(url_for("application_detail", application_id=application.id))

    elif request.method == "GET":
        form.company_name.data = application.company_name
        form.position_title.data = application.position_title
        form.company_website.data = application.company_website
        form.job_posting_url.data = application.job_posting_url
        form.job_description.data = application.job_description
        form.recruiter_email.data = application.recruiter_email
        form.status.data = application.status
        form.salary.data = application.salary
        form.location.data = application.location
        form.visa_sponsorship.data = application.visa_sponsorship
        form.notes.data = decrypt_text(application.notes)
        form.follow_up_date.data = application.follow_up_date
        form.last_contacted_date.data = application.last_contacted_date

    return render_template("add_application.html", form=form, title="Edit Application")


@app.route("/applications/<int:application_id>/delete", methods=["POST"])
@login_required
def delete_application(application_id):
    application = JobApplication.query.get_or_404(application_id)

    if application.user_id != current_user.id:
        flash("You are not authorized to delete this application.", "danger")
        return redirect(url_for("dashboard"))

    company_name = application.company_name

    db.session.delete(application)

    log_action(current_user.id, f"Deleted application for {company_name}")

    flash("Application deleted successfully.", "info")
    return redirect(url_for("dashboard"))


@app.route("/applications/<int:application_id>")
@login_required
def application_detail(application_id):
    application = JobApplication.query.get_or_404(
        application_id
    )

    if application.user_id != current_user.id:
        flash(
            "You are not authorized to view this application.",
            "danger"
        )
        return redirect(url_for("dashboard"))
    
    saved_interview_prep = InterviewPrep.query.filter_by(
        user_id=current_user.id,
        company=application.company_name,
        role=application.position_title
    ).first()

    related_reports = (
        AIReport.query
        .filter_by(user_id=current_user.id)
        .filter(
            db.or_(
                db.and_(
                    AIReport.company.ilike(application.company_name),
                    AIReport.position.ilike(application.position_title)
                ),
                db.and_(
                    AIReport.company.ilike(application.company_name),
                    AIReport.position.is_(None)
                )
            )
        )
        .order_by(AIReport.created_at.desc())
        .all()
    )

    latest_resume = get_latest_resume_for_user(
        current_user.id
    )

    readiness = {
        "resume": bool(
            latest_resume and latest_resume.extracted_text
        ),
        "job_description": bool(
            application.job_description
            and application.job_description.strip()
        ),
        "cover_letter": False,
        "resume_review": False,
        "job_match": False,
        "interview_coach": False,
        "interview_prep": saved_interview_prep is not None,
        "company_intelligence": (
            application.company_intelligence is not None
        ),
        "application_intelligence": False
    }
    
    for report in related_reports:
        if report.report_type == "cover_letter":
            readiness["cover_letter"] = True

        elif report.report_type == "resume_review":
            readiness["resume_review"] = True

        elif report.report_type == "job_match":
            readiness["job_match"] = True

        elif report.report_type == "interview_coach":
            readiness["interview_coach"] = True
            
        elif report.report_type == "application_intelligence":
            readiness["application_intelligence"] = True


    completed_items = sum(readiness.values())
    total_items = len(readiness)

    readiness_percent = (round(completed_items / total_items * 100) if total_items else 0)

    application_summary = []

    if readiness_percent >= 85:
        application_summary.append(
            "This application is highly prepared and ready for final review."
        )
    elif readiness_percent >= 60:
        application_summary.append(
            "This application is partially prepared but still has important gaps."
        )
    else:
        application_summary.append(
            "This application needs more preparation before it is interview-ready."
        )

    if not readiness["job_match"]:
        application_summary.append(
            "Run a job match analysis to identify resume gaps."
        )

    if not readiness["resume_review"]:
        application_summary.append(
            "Generate a resume review tailored to this posting."
        )

    if not readiness["cover_letter"]:
        application_summary.append(
            "Create a tailored cover letter for this application."
        )

    if not readiness["interview_prep"]:
        application_summary.append(
            "Generate structured interview practice questions."
        )

    if not readiness["interview_coach"]:
        application_summary.append(
            "Generate a complete AI interview guide."
        )

    if application.risk_level == "High Risk":
        application_summary.append(
            "Review the company carefully because the current risk level is high."
        )
    elif application.risk_level == "Medium Risk":
        application_summary.append(
            "Complete additional company research before proceeding."
        )


    return render_template(
        "application_detail.html",
        application=application,
        related_reports=related_reports,
        readiness=readiness,
        readiness_percent=readiness_percent,
        latest_resume=latest_resume,
        application_summary=application_summary
    )


@app.route("/applications/<int:application_id>/run-analysis", methods=["POST"])
@login_required
def run_complete_analysis(application_id):
    application = JobApplication.query.get_or_404(application_id)

    if application.user_id != current_user.id:
        flash(
            "You are not authorized to analyze this application.",
            "danger"
        )
        return redirect(url_for("dashboard"))

    latest_resume = get_latest_resume_for_user(current_user.id)

    if not latest_resume or not latest_resume.extracted_text:
        flash(
            "Upload a resume before running the complete analysis.",
            "warning"
        )
        return redirect(
            url_for(
                "application_detail",
                application_id=application.id
            )
        )

    try:
        resume_review = analyze_resume(
            latest_resume.extracted_text,
            application.job_description or ""
        )

        report = AIReport(
            user_id=current_user.id,
            report_type="resume_review",
            company=application.company_name,
            position=application.position_title,
            content=resume_review
        )

        db.session.add(report)
        db.session.commit()

        flash(
            "Resume review generated successfully.",
            "success"
        )

    except RateLimitError as e:
        db.session.rollback()

        print("OPENAI QUOTA ERROR:", repr(e))

        if current_user.is_admin:
            flash(
                "OpenAI API quota has been exceeded. Please check your API billing or credits.",
                "danger"
            )
        else:
            flash(
                "The AI service is temporarily unavailable. Please try again later.",
                "warning"
            )

    except Exception as e:
        print(
            "COMPLETE ANALYSIS RESUME REVIEW ERROR:",
            repr(e)
        )

        db.session.rollback()

        flash(
            "An unexpected error occurred while generating the Resume Review.",
            "warning"
        )

    return redirect(
        url_for(
            "application_detail",
            application_id=application.id
        )
    )


@app.route("/applications/export")
@login_required
def export_applications():
    applications = JobApplication.query.filter_by(
        user_id=current_user.id
    ).all()

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Company",
        "Position",
        "Status",
        "Salary",
        "Visa Sponsorship",
        "Application Date",
        "Follow-Up Date",
        "Last Contacted Date",
        "Trust Score",
        "Risk Level",
        "Company Website",
        "Job Posting URL",
        "Recruiter Email"
    ])

    for app in applications:
        writer.writerow([
            app.company_name,
            app.position_title,
            app.status,
            app.salary or "",
            "Yes" if app.visa_sponsorship else "No",
            app.application_date.strftime("%Y-%m-%d") if app.application_date else "",
            app.follow_up_date.strftime("%Y-%m-%d") if app.follow_up_date else "",
            app.last_contacted_date.strftime("%Y-%m-%d") if app.last_contacted_date else "",
            app.legitimacy_score,
            app.risk_level,
            app.company_website or "",
            app.job_posting_url or "",
            app.recruiter_email or ""
        ])

    log_action(current_user.id, "Exported applications to CSV")

    response = Response(
        output.getvalue(),
        mimetype="text/csv"
    )

    response.headers["Content-Disposition"] = "attachment; filename=applications.csv"

    return response


@app.route("/applications/<int:application_id>/intelligence-report", methods=["POST"])
@login_required
def generate_application_intelligence_report(application_id):
    application = JobApplication.query.get_or_404(application_id)

    if application.user_id != current_user.id:
        flash(
            "You are not authorized to generate this report.",
            "danger"
        )
        return redirect(url_for("dashboard"))

    latest_resume = get_latest_resume_for_user(current_user.id)

    related_reports = (
        AIReport.query
        .filter_by(user_id=current_user.id)
        .filter(
            db.and_(
                AIReport.company.ilike(application.company_name),
                AIReport.position.ilike(application.position_title)
            )
        )
        .order_by(AIReport.created_at.desc())
        .all()
    )

    resume_review = next(
        (
            report.content
            for report in related_reports
            if report.report_type == "resume_review"
        ),
        "No resume review has been generated."
    )

    job_match = next(
        (
            report.content
            for report in related_reports
            if report.report_type == "job_match"
        ),
        "No job match analysis has been generated."
    )

    interview_guide = next(
        (
            report.content
            for report in related_reports
            if report.report_type == "interview_coach"
        ),
        "No interview guide has been generated."
    )

    if application.company_intelligence:
        company_intelligence = (
            "Summary:\n"
            f"{application.company_intelligence.summary or 'Not available'}\n\n"
            "Positive Signals:\n"
            f"{application.company_intelligence.positive_signals or 'None'}\n\n"
            "Risk Signals:\n"
            f"{application.company_intelligence.risk_signals or 'None'}"
        )
    else:
        company_intelligence = (
            "No company intelligence has been generated."
        )

    resume_text = (
        latest_resume.extracted_text
        if latest_resume and latest_resume.extracted_text
        else "No resume is available."
    )
    
    if not can_use_ai(current_user):
        limit = 25 if current_user.plan == "premium" else 5

        flash(
            f"You have reached your daily limit of {limit} AI requests.",
            "warning"
        )

        return redirect(
            url_for(
                "application_detail",
                application_id=application.id
            )
        )

    try:
        report_content = generate_application_intelligence(
            application=application,
            resume_text=resume_text,
            resume_review=resume_review,
            job_match=job_match,
            interview_guide=interview_guide,
            company_intelligence=company_intelligence
        )

        report = AIReport(
            user_id=current_user.id,
            report_type="application_intelligence",
            company=application.company_name,
            position=application.position_title,
            content=report_content
        )

        db.session.add(report)

        record_ai_usage(
            current_user.id,
            "application_intelligence"
        )

        db.session.commit()

        log_action(
            current_user.id,
            f"Generated application intelligence report for "
            f"{application.company_name} - "
            f"{application.position_title}"
        )

        flash(
            "Application intelligence report generated.",
            "success"
        )

        return redirect(
            url_for(
                "view_ai_report",
                report_id=report.id
            )
        )

    except RateLimitError as e:
        db.session.rollback()

        print(
            "APPLICATION INTELLIGENCE QUOTA ERROR:",
            repr(e)
        )

        if current_user.is_admin:
            flash(
                "OpenAI API quota has been exceeded. "
                "Check your API billing or credits.",
                "danger"
            )
        else:
            flash(
                "The AI service is temporarily unavailable. "
                "Please try again later.",
                "warning"
            )

        return redirect(
            url_for(
                "application_detail",
                application_id=application.id
            )
        )

    except Exception as e:
        db.session.rollback()

        print(
            "APPLICATION INTELLIGENCE ERROR:",
            repr(e)
        )

        flash(
            "An unexpected error occurred while generating "
            "the Application Intelligence Report.",
            "warning"
        )

        return redirect(
            url_for(
                "application_detail",
                application_id=application.id
            )
        )


@app.route("/resumes/upload", methods=["GET", "POST"])
@login_required
def upload_resume():
    form = ResumeUploadForm()

    if form.validate_on_submit():
        file = form.resume_file.data
        original_filename = secure_filename(file.filename)

        stored_filename = f"user_{current_user.id}_{original_filename}"
        file_path = os.path.join(
            app.config["UPLOAD_FOLDER"],
            stored_filename,
        )

        # Re-create the directory if it was removed while the app
        # was running or this is a fresh local/container filesystem.
        os.makedirs(
            app.config["UPLOAD_FOLDER"],
            exist_ok=True,
        )

        file.save(file_path)

        extracted_text = extract_resume_text(
            file_path
        )

        resume = Resume(
            filename=stored_filename,
            original_filename=original_filename,
            version_name=form.version_name.data,
            extracted_text=extracted_text,
            user_id=current_user.id
        )

        db.session.add(resume)
        db.session.commit()

        log_action(current_user.id, f"Uploaded resume version: {form.version_name.data}")

        flash("Resume uploaded successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template("upload_resume.html", form=form)


@app.route("/resumes/<int:resume_id>/view")
@login_required
def view_resume(resume_id):
    resume = Resume.query.get_or_404(resume_id)

    if resume.user_id != current_user.id:
        flash("You are not authorized to view this resume.", "danger")
        return redirect(url_for("dashboard"))

    if not resume.original_filename.lower().endswith(".pdf"):
        flash(
            "Browser preview is currently only available for PDF resumes. Download the original file instead.",
            "warning"
        )
        return redirect(url_for("dashboard"))

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        resume.filename,
        as_attachment=False
    )


@app.route("/resumes/<int:resume_id>/download")
@login_required
def download_resume(resume_id):
    resume = Resume.query.get_or_404(resume_id)

    if resume.user_id != current_user.id:
        flash("You are not authorized to download this resume.", "danger")
        return redirect(url_for("dashboard"))

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        resume.filename,
        as_attachment=True,
        download_name=resume.original_filename
    )


@app.route("/resumes/analyze", methods=["GET", "POST"])
@login_required
def resume_analyzer():
    form = ResumeAnalysisForm()
    score = None
    rating = None
    strengths = []
    improvements = []
    
    latest_resume = get_latest_resume_for_user(current_user.id)
    
    if not latest_resume or not latest_resume.extracted_text:
        flash("Upload a resume before analyzing resume strength.", "warning")
        return redirect(url_for("upload_resume"))
    
    if form.validate_on_submit():
        score, rating, strengths, improvements = analyze_resume_text(latest_resume.extracted_text)

        report_content = (
            f"Resume Score: {score}/100\n"
            f"Rating: {rating}\n\n"
            "Strengths:\n"
            + "\n".join(f"- {item}" for item in strengths)
            + "\n\nAreas for Improvement:\n"
            + "\n".join(f"- {item}" for item in improvements)
        )

        report = AIReport(
            user_id=current_user.id,
            report_type="resume_analysis",
            company=None,
            position=None,
            content=report_content
        )

        db.session.add(report)
        db.session.commit()

        log_action(current_user.id, f"Analyzed resume strength. Score: {score}/100 - {rating}")

    return render_template(
        "analyze_resume.html",
        form=form,
        score=score,
        rating=rating,
        strengths=strengths,
        improvements=improvements,
        latest_resume=latest_resume
    )


@app.route("/ai/resume-review", methods=["GET", "POST"])
@login_required
def ai_resume_review():
    form = AIResumeReviewForm()
    latest_resume = get_latest_resume_for_user(current_user.id)
    
    application_id = request.args.get("application_id", type=int)
    application = None

    if application_id:
        application = JobApplication.query.filter_by(
            id=application_id,
            user_id=current_user.id
        ).first_or_404()

    ai_feedback = None
    manual_prompt = None

    if not latest_resume or not latest_resume.extracted_text:
        flash("Upload a resume before running an AI resume review.", "warning")
        return redirect(url_for("upload_resume"))

    if request.method == "GET" and application:
        form.job_description.data = application.job_description or ""

    if form.validate_on_submit():
        
        if not can_use_ai(current_user):
            limit = get_daily_ai_limit(current_user)
            flash(f"You have reached your daily limit of {limit} AI requests.", "warning")

            return render_template(
                "ai_resume_review.html",
                form=form,
                ai_feedback=None,
                manual_prompt=None,
                latest_resume=latest_resume,
                application=application
            )
        
        try:
            ai_feedback = analyze_resume(
                latest_resume.extracted_text,
                form.job_description.data
            )

            report = AIReport(
                user_id=current_user.id,
                report_type="resume_review",
                company=application.company_name if application else None,
                position=application.position_title if application else None,
                content=ai_feedback
            )

            db.session.add(report)
            record_ai_usage(current_user.id, "resume_review")
            db.session.commit()

            log_action(current_user.id, "Ran AI resume review")

        except RateLimitError as e:
            db.session.rollback()

            manual_prompt = build_resume_review_prompt(
                latest_resume.extracted_text,
                form.job_description.data
            )

            if current_user.is_admin:
                flash(
                    "OpenAI API quota has been exceeded. "
                    "Check your API billing or credits. "
                    "You can use the manual prompt below in ChatGPT.",
                    "danger"
                )
            else:
                flash(
                    "The AI service is temporarily unavailable. "
                    "You can use the manual prompt below in ChatGPT.",
                    "warning"
                )

            print("AI RESUME REVIEW QUOTA ERROR:", repr(e))

        except Exception as e:
            db.session.rollback()

            manual_prompt = build_resume_review_prompt(
                latest_resume.extracted_text,
                form.job_description.data
            )

            flash(
                "The AI API is currently unavailable. "
                "Copy the prompt below into ChatGPT.",
                "warning"
            )

            print("AI RESUME REVIEW ERROR:", repr(e))

    return render_template(
        "ai_resume_review.html",
        form=form,
        ai_feedback=ai_feedback,
        manual_prompt=manual_prompt,
        latest_resume=latest_resume,
        application=application
    )


@app.route("/ai/cover-letter", methods=["GET", "POST"])
@login_required
def ai_cover_letter():
    form = AICoverLetterForm()

    latest_resume = get_latest_resume_for_user(current_user.id)

    cover_letter = None
    manual_prompt = None

    application_id = request.args.get("application_id", type=int)
    application = None

    if application_id:
        application = JobApplication.query.filter_by(
            id=application_id,
            user_id=current_user.id
        ).first_or_404()

    if not latest_resume or not latest_resume.extracted_text:
        flash(
            "Upload a resume before generating a cover letter.",
            "warning"
        )
        return redirect(url_for("upload_resume"))

    if request.method == "GET" and application:
        form.company.data = application.company_name
        form.position.data = application.position_title
        form.job_description.data = (
            application.job_description or ""
        )

    if form.validate_on_submit():

        if not can_use_ai(current_user):
            limit = 25 if current_user.plan == "premium" else 5

            flash(
                f"You have reached your daily limit of {limit} AI requests.",
                "warning"
            )

            return render_template(
                "ai_cover_letter.html",
                form=form,
                cover_letter=None,
                manual_prompt=None,
                latest_resume=latest_resume,
                application=application
            )

        try:
            cover_letter = generate_cover_letter(
                form.company.data,
                form.position.data,
                latest_resume.extracted_text,
                form.job_description.data
            )

            report = AIReport(
                user_id=current_user.id,
                report_type="cover_letter",
                company=(
                    application.company_name
                    if application
                    else form.company.data
                ),
                position=(
                    application.position_title
                    if application
                    else form.position.data
                ),
                content=cover_letter
            )

            db.session.add(report)

            record_ai_usage(
                current_user.id,
                "cover_letter"
            )

            db.session.commit()

            log_action(
                current_user.id,
                f"Generated AI cover letter for "
                f"{form.company.data} - {form.position.data}"
            )

        except RateLimitError as e:
            db.session.rollback()

            manual_prompt = build_cover_letter_prompt(
                form.company.data,
                form.position.data,
                latest_resume.extracted_text,
                form.job_description.data
            )

            if current_user.is_admin:
                flash(
                    "OpenAI API quota has been exceeded. "
                    "Check your API billing or credits. "
                    "You can use the manual prompt below in ChatGPT.",
                    "danger"
                )
            else:
                flash(
                    "The AI service is temporarily unavailable. "
                    "You can use the manual prompt below in ChatGPT.",
                    "warning"
                )

            print(
                "AI COVER LETTER QUOTA ERROR:",
                repr(e)
            )

        except Exception as e:
            db.session.rollback()

            manual_prompt = build_cover_letter_prompt(
                form.company.data,
                form.position.data,
                latest_resume.extracted_text,
                form.job_description.data
            )

            flash(
                "The AI API is currently unavailable. "
                "Copy the prompt below into ChatGPT.",
                "warning"
            )

            print(
                "AI COVER LETTER ERROR:",
                repr(e)
            )

    return render_template(
        "ai_cover_letter.html",
        form=form,
        cover_letter=cover_letter,
        manual_prompt=manual_prompt,
        latest_resume=latest_resume,
        application=application
    )


@app.route("/interview-prep", methods=["GET", "POST"])
@login_required
def interview_prep():
    form = InterviewPrepForm()

    behavioral_questions = None
    technical_questions = None
    study_topics = None

    application_id = request.args.get("application_id", type=int)
    application = None

    if application_id:
        application = JobApplication.query.filter_by(
            id=application_id,
            user_id=current_user.id
        ).first_or_404()

    if request.method == "GET" and application:
        form.company.data = application.company_name
        form.role.data = application.position_title
        form.job_description.data = application.job_description or ""

    if form.validate_on_submit():
        behavioral_questions, technical_questions, study_topics = (
            generate_interview_prep(
                form.company.data,
                form.role.data,
                form.job_description.data
            )
        )

        saved_prep = InterviewPrep(
            company=form.company.data,
            role=form.role.data,
            behavioral_questions=json.dumps(behavioral_questions),
            technical_questions=json.dumps(technical_questions),
            study_topics=json.dumps(study_topics),
            user_id=current_user.id
        )

        db.session.add(saved_prep)
        db.session.commit()

        log_action(
            current_user.id,
            f"Saved interview prep for "
            f"{form.company.data} - {form.role.data}"
        )

    return render_template(
        "interview_prep.html",
        form=form,
        behavioral_questions=behavioral_questions,
        technical_questions=technical_questions,
        study_topics=study_topics,
        application=application
    )


@app.route("/ai/interview-coach", methods=["GET", "POST"])
@login_required
def ai_interview_coach():
    form = AIInterviewCoachForm()
    latest_resume = get_latest_resume_for_user(current_user.id)

    application_id = request.args.get("application_id", type=int)
    application = None

    if application_id:
        application = JobApplication.query.filter_by(
            id=application_id,
            user_id=current_user.id
        ).first_or_404()

    interview_prep = None
    manual_prompt = None

    if not latest_resume or not latest_resume.extracted_text:
        flash(
            "Upload a resume before generating interview prep.",
            "warning"
        )
        return redirect(url_for("upload_resume"))

    if request.method == "GET" and application:
        form.company.data = application.company_name
        form.position.data = application.position_title
        form.job_description.data = application.job_description or ""

    if form.validate_on_submit():

        if not can_use_ai(current_user):
            limit = get_daily_ai_limit(current_user)

            flash(
                f"You have reached your daily limit of {limit} AI requests.",
                "warning"
            )

            return render_template(
                "ai_interview_coach.html",
                form=form,
                interview_prep=None,
                manual_prompt=None,
                latest_resume=latest_resume,
                application=application
            )

        try:
            interview_prep = generate_interview_coach(
                form.company.data,
                form.position.data,
                form.job_description.data,
                latest_resume.extracted_text
            )

            report = AIReport(
                user_id=current_user.id,
                report_type="interview_coach",
                company=(
                    application.company_name
                    if application
                    else form.company.data
                ),
                position=(
                    application.position_title
                    if application
                    else form.position.data
                ),
                content=interview_prep
            )

            db.session.add(report)

            record_ai_usage(
                current_user.id,
                "interview_coach"
            )

            db.session.commit()

            log_action(
                current_user.id,
                f"Generated AI interview prep for "
                f"{form.company.data} - {form.position.data}"
            )

        except RateLimitError as e:
            db.session.rollback()

            manual_prompt = build_interview_coach_prompt(
                form.company.data,
                form.position.data,
                form.job_description.data,
                latest_resume.extracted_text
            )

            if current_user.is_admin:
                flash(
                    "OpenAI API quota has been exceeded. "
                    "Check your API billing or credits. "
                    "You can use the manual prompt below in ChatGPT.",
                    "danger"
                )
            else:
                flash(
                    "The AI service is temporarily unavailable. "
                    "You can use the manual prompt below in ChatGPT.",
                    "warning"
                )

            print(
                "AI INTERVIEW COACH QUOTA ERROR:",
                repr(e)
            )

        except Exception as e:
            db.session.rollback()

            manual_prompt = build_interview_coach_prompt(
                form.company.data,
                form.position.data,
                form.job_description.data,
                latest_resume.extracted_text
            )

            flash(
                "The AI API is currently unavailable. "
                "Copy the prompt below into ChatGPT.",
                "warning"
            )

            print(
                "AI INTERVIEW COACH ERROR:",
                repr(e)
            )

    return render_template(
        "ai_interview_coach.html",
        form=form,
        interview_prep=interview_prep,
        manual_prompt=manual_prompt,
        latest_resume=latest_resume,
        application=application
    )


@app.route("/ai/reports")
@login_required
def ai_reports():
    selected_type = request.args.get("type", "all")
    search_term = request.args.get("search", "").strip()

    query = AIReport.query.filter_by(user_id=current_user.id)

    if selected_type == "resume":
        query = query.filter(
            AIReport.report_type.in_([
                "resume_analysis",
                "resume_review"
            ])
        )

    elif selected_type in {
        "job_match",
        "cover_letter",
        "interview_coach"
    }:
        query = query.filter_by(report_type=selected_type)

    if search_term:
        search_pattern = f"%{search_term}%"

        query = query.filter(
            db.or_(
                AIReport.company.ilike(search_pattern),
                AIReport.position.ilike(search_pattern),
                AIReport.report_type.ilike(search_pattern),
                AIReport.content.ilike(search_pattern)
            )
        )

    reports = (
        query
        .order_by(AIReport.created_at.desc())
        .all()
    )

    return render_template(
        "ai_reports.html",
        reports=reports,
        selected_type=selected_type,
        search_term=search_term
    )


@app.route("/ai/reports/<int:report_id>")
@login_required
def view_ai_report(report_id):
    report = AIReport.query.get_or_404(report_id)
    
    if report.user_id != current_user.id:
        flash("You are not authorized to view this report", "danger")
        return redirect(url_for("ai_reports"))
    
    return render_template(
        "view_ai_report.html",
        report=report
    )


@app.route("/ai/reports/<int:report_id>/delete")
@login_required
def delete_ai_report(report_id):
    report = AIReport.query.get_or_404(report_id)
    
    if report.user_id != current_user.id:
        flash("You are not authotized to delete this report", "danger")
        return redirect(url_for("ai_reports"))
    
    report_type = report.report_type
    
    
    db.sessions.delete(report)
    db.sessions.commit()
    
    log_action(current_user.id, f"Deleted AI Report: {report_type}")
    
    flash("Report has been deleted successfully.", "success")
    return redirect(url_for("ai_reports"))
    

@app.route("/company-lookup", methods=["GET", "POST"])
@login_required
def company_lookup():
    form = CompanyLookupForm()

    score = None
    risk_level = None
    strengths = None
    warnings = None

    if form.validate_on_submit():

        score, risk_level, strengths, warnings = analyze_company(
            form.company_name.data
        )

        log_action(
            current_user.id,
            f"Performed company reputation lookup for {form.company_name.data}"
        )

    return render_template(
        "company_lookup.html",
        form=form,
        score=score,
        risk_level=risk_level,
        strengths=strengths,
        warnings=warnings
    )


@app.route("/applications/<int:application_id>/company-intelligence/generate", methods=["POST"])
@login_required
def generate_company_intelligence(application_id):
    application = JobApplication.query.get_or_404(application_id)

    if application.user_id != current_user.id:
        flash(
            "You are not authorized to analyze this application.",
            "danger"
        )
        return redirect(url_for("dashboard"))

    score, risk_level, strengths, warnings = analyze_company(
        application.company_name
    )

    intelligence = application.company_intelligence

    if intelligence is None:
        intelligence = CompanyIntelligence(
            user_id=current_user.id,
            application_id=application.id,
            company_name=application.company_name
        )

        db.session.add(intelligence)

    intelligence.company_name = application.company_name

    intelligence.positive_signals = "\n".join(
        f"- {item}" for item in strengths
    )

    intelligence.risk_signals = "\n".join(
        f"- {item}" for item in warnings
    )

    intelligence.summary = (
        f"Trust Score: {score}/100\n"
        f"Risk Level: {risk_level}"
    )

    # Keep the original application record synchronized.
    application.legitimacy_score = score
    application.risk_level = risk_level

    db.session.commit()

    log_action(
        current_user.id,
        f"Generated company intelligence for "
        f"{application.company_name}"
    )

    flash(
        "Company intelligence generated successfully.",
        "success"
    )

    return redirect(
        url_for(
            "application_detail",
            application_id=application.id
        )
    )


@app.route("/jobs/import-url", methods=["GET", "POST"])
@login_required
def import_job_url():
    form = JobUrlImportForm()
    extracted_job = None

    if form.import_submit.data and form.validate_on_submit():
        try:
            extracted_job = extract_job_from_url(form.job_url.data)

            visa_value = extracted_job.get("visa_sponsorship")

            if visa_value in [True, "True", "true", "Yes", "yes"]:
                visa_value = "Yes"
            elif visa_value in [False, "False", "false", "No", "no"]:
                visa_value = "No"
            else:
                visa_value = "Unknown"

            form.company_name.data = extracted_job.get("company_name", "")
            form.position_title.data = (extracted_job.get("position_title") or extracted_job.get("page_title", ""))
            form.salary.data = extracted_job.get("salary", "")
            form.visa_sponsorship.data = visa_value
            form.location.data = extracted_job.get("location", "")
            form.job_description.data = extracted_job.get("job_description", "")

            flash("Job posting imported successfully.", "success")

        except Exception as e:
            flash(
                f"Could not import job posting: {str(e)}",
                "danger"
            )

    elif form.save_submit.data and form.validate_on_submit():
        application = JobApplication(
            company_name=(form.company_name.data or "Unknown Company"),
            position_title=(form.position_title.data or "Unknown Position"),
            job_posting_url=form.job_url.data,
            job_description=(form.job_description.data or ""),
            salary=form.salary.data,
            location=form.location.data,
            visa_sponsorship=(form.visa_sponsorship.data or "Unknown"),
            status="Applied",
            notes=encrypt_text(""),
            user_id=current_user.id
        )

        db.session.add(application)
        db.session.flush()

        history_entry = ApplicationHistory(
            status=application.status,
            note="Application created from imported job posting",
            application_id=application.id
        )

        db.session.add(history_entry)
        db.session.commit()

        log_action(
            current_user.id,
            f"Saved imported job application: "
            f"{application.company_name}"
        )

        flash(
            "Imported job saved as application.",
            "success"
        )

        return redirect(
            url_for(
                "application_detail",
                application_id=application.id
            )
        )

    return render_template(
        "import_job_url.html",
        form=form,
        extracted_job=extracted_job
    )


@app.route("/api/locations/countries")
@login_required
def location_countries_api():
    try:
        return jsonify({
            "success": True,
            "items": get_countries(),
        })
    except LocationDataUnavailable as error:
        return jsonify({
            "success": False,
            "message": str(error),
            "items": [],
        }), 503


@app.route("/api/locations/states")
@login_required
def location_states_api():
    country_code = (
        request.args.get("country", "")
        .strip()
        .upper()
    )

    if not country_code:
        return jsonify({
            "success": True,
            "items": [],
        })

    try:
        return jsonify({
            "success": True,
            "items": get_states(country_code),
        })
    except LocationDataUnavailable as error:
        return jsonify({
            "success": False,
            "message": str(error),
            "items": [],
        }), 503


@app.route("/api/locations/cities")
@login_required
def location_cities_api():
    country_code = (
        request.args.get("country", "")
        .strip()
        .upper()
    )
    state_code = (
        request.args.get("state", "")
        .strip()
    )

    if not country_code or not state_code:
        return jsonify({
            "success": True,
            "items": [],
        })

    try:
        return jsonify({
            "success": True,
            "items": get_cities(
                country_code,
                state_code,
            ),
        })
    except LocationDataUnavailable as error:
        return jsonify({
            "success": False,
            "message": str(error),
            "items": [],
        }), 503


@app.route("/auto-apply/applicant-profile", methods=["GET", "POST"])
@login_required
def auto_apply_applicant_profile():
    access = get_auto_apply_access(current_user)

    if not access["allowed"]:
        flash(
            "Auto Apply is available to Premium users and administrators.",
            "warning",
        )
        return redirect(url_for("search_profiles"))

    profile = ApplicantProfile.query.filter_by(
        user_id=current_user.id
    ).first()

    form = ApplicantProfileForm(obj=profile)

    form.phone_country_iso.choices = [
        ("", "Choose phone country"),
        *get_phone_country_choices(),
    ]

    if request.method == "GET":
        preferred_region = (
            country_region_from_name(profile.country)
            if profile
            else ""
        )

        phone_region, national_number = split_phone_for_form(
            profile.phone if profile else None,
            preferred_region=preferred_region,
        )

        form.phone_country_iso.data = (
            phone_region
            or preferred_region
            or ""
        )
        form.phone.data = national_number

    if form.validate_on_submit():
        try:
            normalized_phone = normalize_phone_number(
                form.phone.data,
                form.phone_country_iso.data,
            )
        except ValueError as error:
            form.phone.errors.append(str(error))
        else:
            if profile is None:
                profile = ApplicantProfile(
                    user_id=current_user.id
                )
                db.session.add(profile)

            profile.first_name = form.first_name.data.strip()
            profile.last_name = form.last_name.data.strip()
            profile.phone = normalized_phone

            profile.country = (
                (form.country.data or "").strip()
                or None
            )
            profile.state_region = (
                (form.state_region.data or "").strip()
                or None
            )
            profile.city = (
                (form.city.data or "").strip()
                or None
            )
            profile.postal_code = (
                (form.postal_code.data or "").strip()
                or None
            )

            # Professional links are intentionally optional.
            profile.linkedin_url = (
                (form.linkedin_url.data or "").strip()
                or None
            )
            profile.github_url = (
                (form.github_url.data or "").strip()
                or None
            )
            profile.website_url = (
                (form.website_url.data or "").strip()
                or None
            )

            db.session.commit()

            log_action(
                current_user.id,
                "Updated Auto Apply applicant profile",
            )

            flash(
                "Auto Apply applicant profile saved.",
                "success",
            )

            return redirect(
                url_for("auto_apply_queue")
            )

    return render_template(
        "auto_apply_applicant_profile.html",
        form=form,
    )


@app.route("/auto-apply")
@login_required
def auto_apply_queue():
    auto_apply_access = get_auto_apply_access(
        current_user
    )

    if not auto_apply_access["allowed"]:
        flash(
            "Auto Apply is available to Premium "
            "users and administrators.",
            "warning",
        )
        return redirect(
            url_for("search_profiles")
        )

    page = request.args.get("page", 1, type=int)
    selected_status = request.args.get("status", "all").strip()
    allowed = {"all", "Pending Review", "Approved", "Rejected"}
    if selected_status not in allowed:
        selected_status = "all"

    query = AutoApplyCandidate.query.filter_by(user_id=current_user.id)
    if selected_status != "all":
        query = query.filter_by(status=selected_status)

    pagination = (
        query.order_by(AutoApplyCandidate.created_at.desc())
        .paginate(page=page, per_page=25, error_out=False)
    )
    status_counts = {
        status: count
        for status, count in (
            db.session.query(AutoApplyCandidate.status, db.func.count(AutoApplyCandidate.id))
            .filter(AutoApplyCandidate.user_id == current_user.id)
            .group_by(AutoApplyCandidate.status)
            .all()
        )
    }
    return render_template(
        "auto_apply_queue.html",
        candidates=pagination.items,
        pagination=pagination,
        selected_status=selected_status,
        status_counts=status_counts,
        applicant_profile=ApplicantProfile.query.filter_by(user_id=current_user.id).first(),
    )


@app.route("/auto-apply/<int:candidate_id>/<string:action>", methods=["POST"])
@login_required
def update_auto_apply_candidate(candidate_id, action):
    auto_apply_access = get_auto_apply_access(
        current_user
    )

    if not auto_apply_access["allowed"]:
        flash(
            "Auto Apply is available to Premium "
            "users and administrators.",
            "warning",
        )
        return redirect(
            url_for("search_profiles")
        )

    candidate = AutoApplyCandidate.query.filter_by(
        id=candidate_id,
        user_id=current_user.id,
    ).first_or_404()

    action = str(action or "").strip().lower()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if action == "approve":
        result = execute_candidate_submission(candidate, current_user)
        message = result["message"]
        category = result["category"]
    elif action == "reject":
        candidate.status = "Rejected"
        candidate.reviewed_at = now
        message = "Candidate rejected."
        category = "info"
    elif action == "reset":
        candidate.status = "Pending Review"
        candidate.reviewed_at = None
        message = "Candidate returned to Pending Review."
        category = "info"
    else:
        flash("That Auto Apply action is not valid.", "warning")
        return redirect(url_for("auto_apply_queue"))

    db.session.commit()
    log_action(
        current_user.id,
        f"Auto Apply {action}: {candidate.discovered_job.company_name} - {candidate.discovered_job.position_title}",
    )
    flash(message, category)
    return redirect(request.referrer or url_for("auto_apply_queue"))


@app.route("/search-profiles")
@login_required
def search_profiles():
    profiles = JobSearchProfile.query.filter_by(
        user_id=current_user.id
    ).order_by(
        JobSearchProfile.created_at.desc()
    ).all()

    return render_template(
        "search_profiles.html",
        profiles=profiles
    )


@app.route("/search-profiles/new", methods=["GET", "POST"])
@login_required
def new_search_profile():
    form = JobSearchProfileForm()
    configure_search_profile_auto_apply_form(form, current_user.id)

    if (
        request.method == "GET"
        and not form.auto_apply_contact_email.data
    ):
        form.auto_apply_contact_email.data = (
            current_user.email
        )

    if form.validate_on_submit():
        auto_apply_access = get_auto_apply_access(
            current_user
        )

        auto_apply_enabled = bool(
            auto_apply_access["allowed"]
            and form.auto_apply_enabled.data
        )

        auto_apply_resume_id = (
            form.auto_apply_resume_id.data
            if auto_apply_access["allowed"]
            else None
        ) or None

        if auto_apply_access["unlimited"]:
            # Stored for schema compatibility; ignored for Admin.
            auto_apply_daily_limit = 50
        else:
            auto_apply_daily_limit = max(
                1,
                min(
                    int(
                        form.auto_apply_daily_limit.data
                        or 50
                    ),
                    50,
                ),
            )

        selected_workplace_types = (
            form.workplace_types.data
            or ["remote"]
        )

        profile = JobSearchProfile(
            user_id=current_user.id,
            name=form.name.data,
            keywords=form.keywords.data,
            locations=form.locations.data,
            employment_types=",".join(form.employment_types.data or ["all"]),
            workplace_types=",".join(
                selected_workplace_types
            ),
            # Keep the old field synchronized temporarily
            # while the rest of the app moves to workplace_types.
            remote_only=(
                selected_workplace_types
                == ["remote"]
            ),
            visa_required=(
                form.visa_preference.data
                == "yes"
            ),
            minimum_salary=form.minimum_salary.data,
            active=form.active.data,
            experience_levels=",".join(
                form.experience_levels.data or []
            ),
            remote_scope=form.remote_scope.data,
            visa_preference=form.visa_preference.data,
            overseas_applicant_preference=(
                form.overseas_applicant_preference.data
            ),
            maximum_posting_age_days=int(
                form.maximum_posting_age_days.data
            ),
            auto_apply_enabled=auto_apply_enabled,
            auto_apply_resume_id=auto_apply_resume_id,
            auto_apply_cover_letter_mode=(
                form.auto_apply_cover_letter_mode.data
            ),
            auto_apply_contact_email=(
                (
                    form.auto_apply_contact_email.data
                    or current_user.email
                )
                .strip()
                .lower()
                if auto_apply_access["allowed"]
                else None
            ),
            auto_apply_excluded_companies=(
                (
                    form.auto_apply_excluded_companies.data
                    or ""
                ).strip()
                or None
            ),
            auto_apply_daily_limit=(
                auto_apply_daily_limit
            ),
        )

        try:
            db.session.add(profile)
            db.session.commit()

            log_action(
                current_user.id,
                f"Created search profile '{profile.name}'"
            )

            flash(
                "Search profile created successfully.",
                "success"
            )

            return redirect(url_for("search_profiles"))

        except Exception as error:
            db.session.rollback()

            print(
                "SEARCH PROFILE SAVE ERROR:",
                repr(error),
            )

            flash(
                "The search profile could not be saved.",
                "danger"
            )

    if request.method == "POST":
        print(
            "SEARCH PROFILE FORM ERRORS:",
            form.errors,
        )

        if form.errors:
            flash(
                "The search profile could not be saved. "
                "Check the form fields and try again.",
                "danger"
            )

    return render_template(
        "search_profile_form.html",
        form=form,
        title="New Search Profile"
    )


@app.route("/search-profiles/<int:profile_id>/edit", methods=["GET", "POST"])
@login_required
def edit_search_profile(profile_id):
    profile = JobSearchProfile.query.filter_by(
        id=profile_id,
        user_id=current_user.id
    ).first_or_404()

    form = JobSearchProfileForm(obj=profile)
    configure_search_profile_auto_apply_form(form, current_user.id)

    if request.method == "GET":
        form.experience_levels.data = [
            value.strip()
            for value in (
                profile.experience_levels or ""
            ).split(",")
            if value.strip()
        ]

        form.workplace_types.data = [
            value.strip()
            for value in (
                profile.workplace_types
                or "remote"
            ).split(",")
            if value.strip()
        ]

        stored_employment_types = [
            value.strip().lower()
            for value in (
                profile.employment_types
                or "all"
            ).split(",")
            if value.strip()
        ]

        form.employment_types.data = (
            stored_employment_types
            or ["all"]
        )

        form.remote_scope.data = (
            profile.remote_scope
            or "any"
        )

        form.visa_preference.data = (
            profile.visa_preference
            or "any"
        )

        form.overseas_applicant_preference.data = (
            profile.overseas_applicant_preference
            or "any"
        )

        stored_posting_age = min(
            int(
                profile.maximum_posting_age_days
                or 60
            ),
            60,
        )

        allowed_posting_ages = (
            1,
            7,
            14,
            30,
            60,
        )

        selected_posting_age = min(
            allowed_posting_ages,
            key=lambda value: abs(
                value - stored_posting_age
            ),
        )

        form.maximum_posting_age_days.data = str(
            selected_posting_age
        )
        form.auto_apply_resume_id.data = profile.auto_apply_resume_id or 0
        form.auto_apply_contact_email.data = (
            profile.auto_apply_contact_email
            or current_user.email
        )
        form.auto_apply_cover_letter_mode.data = profile.auto_apply_cover_letter_mode or "when_required"
        form.auto_apply_daily_limit.data = profile.auto_apply_daily_limit or 10

    if form.validate_on_submit():
        auto_apply_access = get_auto_apply_access(
            current_user
        )

        auto_apply_enabled = bool(
            auto_apply_access["allowed"]
            and form.auto_apply_enabled.data
        )

        auto_apply_resume_id = (
            form.auto_apply_resume_id.data
            if auto_apply_access["allowed"]
            else None
        ) or None

        if auto_apply_access["unlimited"]:
            # Stored for schema compatibility; ignored for Admin.
            auto_apply_daily_limit = 50
        else:
            auto_apply_daily_limit = max(
                1,
                min(
                    int(
                        form.auto_apply_daily_limit.data
                        or 50
                    ),
                    50,
                ),
            )

        selected_workplace_types = (
            form.workplace_types.data
            or ["remote"]
        )

        profile.name = form.name.data
        profile.keywords = form.keywords.data
        profile.locations = form.locations.data
        profile.employment_types = ",".join(form.employment_types.data or ["all"])

        profile.experience_levels = ",".join(
            form.experience_levels.data or []
        )

        profile.workplace_types = ",".join(
            selected_workplace_types
        )

        profile.remote_scope = form.remote_scope.data
        profile.visa_preference = form.visa_preference.data
        profile.overseas_applicant_preference = (
            form.overseas_applicant_preference.data
        )

        profile.maximum_posting_age_days = int(
            form.maximum_posting_age_days.data
        )

        # Keep the old fields synchronized temporarily.
        profile.remote_only = (
            selected_workplace_types
            == ["remote"]
        )

        profile.visa_required = (
            form.visa_preference.data == "yes"
        )

        profile.minimum_salary = form.minimum_salary.data
        profile.auto_apply_enabled = (
            auto_apply_enabled
        )
        profile.auto_apply_resume_id = (
            auto_apply_resume_id
        )
        profile.auto_apply_cover_letter_mode = (
            form.auto_apply_cover_letter_mode.data
        )
        profile.auto_apply_contact_email = (
            (
                form.auto_apply_contact_email.data
                or current_user.email
            )
            .strip()
            .lower()
            if auto_apply_access["allowed"]
            else None
        )
        profile.auto_apply_excluded_companies = (
            (
                form.auto_apply_excluded_companies.data
                or ""
            ).strip()
            or None
        )
        profile.auto_apply_daily_limit = (
            auto_apply_daily_limit
        )
        profile.active = form.active.data

        db.session.commit()

        auto_apply_stage_stats = None

        if profile.auto_apply_enabled:
            auto_apply_stage_stats = (
                stage_existing_auto_apply_matches(
                    profile
                )
            )
            db.session.commit()

            print(
                "AUTO APPLY BACKFILL | "
                f"Profile: {profile.name} | "
                f"Considered: {auto_apply_stage_stats['considered']} | "
                f"Staged: {auto_apply_stage_stats['staged']} | "
                f"Already queued: {auto_apply_stage_stats['already_queued']} | "
                f"Already applied: {auto_apply_stage_stats['already_applied']} | "
                f"Ignored: {auto_apply_stage_stats['ignored']} | "
                f"Excluded: {auto_apply_stage_stats['excluded_company']}"
            )

        log_action(
            current_user.id,
            f"Updated search profile '{profile.name}'"
        )

        flash(
            "Search profile updated successfully.",
            "success"
        )

        return redirect(
            url_for("search_profiles")
        )

    return render_template(
        "search_profile_form.html",
        form=form,
        title="Edit Search Profile"
    )



@app.route("/search-profiles/<int:profile_id>/delete", methods=["POST"])
@login_required
def delete_search_profile(profile_id):
    profile = JobSearchProfile.query.filter_by(
        id=profile_id,
        user_id=current_user.id
    ).first_or_404()

    profile_name = profile.name

    db.session.delete(profile)
    db.session.commit()

    log_action(
        current_user.id,
        f"Deleted search profile '{profile_name}'"
    )

    flash("Search profile deleted.", "success")
    return redirect(url_for("search_profiles"))


@app.route("/search-profiles/<int:profile_id>/toggle", methods=["POST"])
@login_required
def toggle_search_profile(profile_id):
    profile = JobSearchProfile.query.filter_by(
        id=profile_id,
        user_id=current_user.id
    ).first_or_404()

    profile.active = not profile.active
    db.session.commit()

    status = "activated" if profile.active else "paused"

    log_action(
        current_user.id,
        f"{status.title()} search profile '{profile.name}'"
    )

    flash(
        f"Search profile {status}.",
        "success"
    )

    return redirect(url_for("search_profiles"))


@app.route("/saved-jobs")
@login_required
def saved_discovered_jobs():
    jobs = (
        DiscoveredJob.query
        .filter_by(
            user_id=current_user.id,
            is_saved=True,
            is_ignored=False,
        )
        .order_by(
            DiscoveredJob.saved_at.desc(),
            DiscoveredJob.discovered_at.desc(),
        )
        .all()
    )

    job_url_by_id = {}
    job_url_variants = set()

    for job in jobs:
        canonical_url = canonical_job_posting_url(
            job.posting_url
        )

        if not canonical_url:
            continue

        job_url_by_id[job.id] = canonical_url
        job_url_variants.add(canonical_url)
        job_url_variants.add(f"{canonical_url}/")

    applied_by_url = {}

    if job_url_variants:
        existing_applications = (
            JobApplication.query
            .filter(
                JobApplication.user_id == current_user.id,
                JobApplication.job_posting_url.in_(job_url_variants),
            )
            .all()
        )

        for application in existing_applications:
            application_url = canonical_job_posting_url(
                application.job_posting_url
            )

            if application_url:
                applied_by_url[application_url] = application.id

    applied_application_by_job_id = {
        job_id: applied_by_url[canonical_url]
        for job_id, canonical_url in job_url_by_id.items()
        if canonical_url in applied_by_url
    }

    return render_template(
        "saved_discovered_jobs.html",
        jobs=jobs,
        applied_application_by_job_id=(
            applied_application_by_job_id
        ),
    )


@app.route("/discovered-jobs")
@login_required
def discovered_jobs():
    page = request.args.get(
        "page",
        1,
        type=int,
    )
    selected_profile_id = request.args.get(
        "profile_id",
        type=int,
    )

    profiles = (
        JobSearchProfile.query
        .filter_by(
            user_id=current_user.id
        )
        .order_by(
            JobSearchProfile.created_at.desc()
        )
        .all()
    )

    valid_profile_ids = {
        profile.id
        for profile in profiles
    }

    if (
        selected_profile_id
        and selected_profile_id
        not in valid_profile_ids
    ):
        selected_profile_id = None

    query = (
        DiscoveredJob.query
        .filter_by(
            user_id=current_user.id,
            is_ignored=False,
        )
    )

    if selected_profile_id:
        query = query.filter(
            DiscoveredJob.matched_profiles.any(
                JobSearchProfile.id
                == selected_profile_id
            )
        )

    pagination = (
        query
        .order_by(
            DiscoveredJob.discovered_at.desc()
        )
        .paginate(
            page=page,
            per_page=20,
            error_out=False,
        )
    )

    page_jobs = pagination.items

    job_url_by_id = {}
    job_url_variants = set()

    for job in page_jobs:
        canonical_url = canonical_job_posting_url(
            job.posting_url
        )

        if not canonical_url:
            continue

        job_url_by_id[job.id] = canonical_url
        job_url_variants.add(canonical_url)
        job_url_variants.add(
            f"{canonical_url}/"
        )

    applied_by_url = {}

    if job_url_variants:
        existing_applications = (
            JobApplication.query
            .filter(
                JobApplication.user_id
                == current_user.id,
                JobApplication.job_posting_url.in_(
                    job_url_variants
                ),
            )
            .all()
        )

        for application in existing_applications:
            application_url = (
                canonical_job_posting_url(
                    application.job_posting_url
                )
            )

            if application_url:
                applied_by_url[
                    application_url
                ] = application.id

    applied_application_by_job_id = {
        job_id: applied_by_url[canonical_url]
        for job_id, canonical_url
        in job_url_by_id.items()
        if canonical_url in applied_by_url
    }

    return render_template(
        "discovered_jobs.html",
        jobs=page_jobs,
        pagination=pagination,
        profiles=profiles,
        selected_profile_id=selected_profile_id,
        applied_application_by_job_id=(
            applied_application_by_job_id
        ),
    )



@app.route(
    "/discovered-jobs/<int:job_id>/mark-applied",
    methods=["POST"],
)
@login_required
def mark_discovered_job_applied(job_id):
    job = DiscoveredJob.query.filter_by(
        id=job_id,
        user_id=current_user.id,
    ).first_or_404()

    posting_url = canonical_job_posting_url(
        job.posting_url
    )

    if not posting_url:
        message = (
            "This discovered job does not have "
            "a usable posting URL."
        )

        if request.headers.get(
            "X-Requested-With"
        ) == "XMLHttpRequest":
            return jsonify({
                "success": False,
                "job_id": job.id,
                "action": "applied",
                "message": message,
            }), 400

        flash(message, "danger")
        return redirect(
            request.referrer
            or url_for("discovered_jobs")
        )

    posting_url_variants = {
        posting_url,
        f"{posting_url}/",
    }

    existing_application = (
        JobApplication.query
        .filter(
            JobApplication.user_id
            == current_user.id,
            JobApplication.job_posting_url.in_(
                posting_url_variants
            ),
        )
        .first()
    )

    if existing_application is not None:
        message = (
            "This job is already in Applications."
        )

        if request.headers.get(
            "X-Requested-With"
        ) == "XMLHttpRequest":
            return jsonify({
                "success": True,
                "job_id": job.id,
                "action": "applied",
                "application_id": (
                    existing_application.id
                ),
                "created": False,
                "message": message,
            })

        flash(message, "info")
        return redirect(
            request.referrer
            or url_for("discovered_jobs")
        )

    if len(posting_url) > 255:
        message = (
            "This posting URL is too long for "
            "the current application tracker. "
            "No application was created."
        )

        if request.headers.get(
            "X-Requested-With"
        ) == "XMLHttpRequest":
            return jsonify({
                "success": False,
                "job_id": job.id,
                "action": "applied",
                "message": message,
            }), 400

        flash(message, "warning")
        return redirect(
            request.referrer
            or url_for("discovered_jobs")
        )

    recruiter_email = (
        str(job.recruiter_email or "").strip()
        or None
    )

    if (
        recruiter_email
        and len(recruiter_email) > 120
    ):
        recruiter_email = None

    application = JobApplication(
        company_name=str(
            job.company_name
            or "Unknown Company"
        )[:100],
        position_title=str(
            job.position_title
            or "Unknown Position"
        )[:100],
        job_posting_url=posting_url,
        job_description=(
            job.job_description
            or ""
        ),
        recruiter_email=recruiter_email,
        status="Applied",
        salary=(
            str(job.salary)[:50]
            if job.salary
            else None
        ),
        location=(
            str(job.location)[:100]
            if job.location
            else None
        ),
        visa_sponsorship=str(
            job.visa_sponsorship
            or "Unknown"
        )[:20],
        notes=encrypt_text(""),
        user_id=current_user.id,
    )

    try:
        db.session.add(application)
        db.session.flush()

        db.session.add(
            ApplicationHistory(
                status="Applied",
                note=(
                    "Application created from "
                    "discovered job"
                ),
                application_id=application.id,
            )
        )

        db.session.commit()

    except Exception as error:
        db.session.rollback()
        print(
            "DISCOVERED JOB MARK APPLIED ERROR:",
            repr(error),
        )

        message = (
            "The application could not be "
            "created. Please try again."
        )

        if request.headers.get(
            "X-Requested-With"
        ) == "XMLHttpRequest":
            return jsonify({
                "success": False,
                "job_id": job.id,
                "action": "applied",
                "message": message,
            }), 500

        flash(message, "danger")
        return redirect(
            request.referrer
            or url_for("discovered_jobs")
        )

    log_action(
        current_user.id,
        (
            "Marked discovered job as applied: "
            f"{application.company_name} - "
            f"{application.position_title}"
        ),
    )

    message = "Added to Applications."

    if request.headers.get(
        "X-Requested-With"
    ) == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "job_id": job.id,
            "action": "applied",
            "application_id": application.id,
            "created": True,
            "message": message,
        })

    flash(message, "success")
    return redirect(
        request.referrer
        or url_for("discovered_jobs")
    )


@app.route("/discovered-jobs/<int:job_id>/save", methods=["POST"],)
@login_required
def save_discovered_job(job_id):
    job = DiscoveredJob.query.filter_by(
        id=job_id,
        user_id=current_user.id,
    ).first_or_404()

    job.is_saved = True
    job.is_ignored = False
    job.saved_at = datetime.now(
        timezone.utc
    )
    job.ignored_at = None

    db.session.commit()

    message = (
        f"{job.position_title} "
        f"was saved for later."
    )

    return discovered_job_action_response(
        job=job,
        action="save",
        message=message,
    )


@app.route("/discovered-jobs/ignored")
@login_required
def ignored_discovered_jobs():
    jobs = (
        DiscoveredJob.query
        .filter_by(
            user_id=current_user.id,
            is_ignored=True
        )
        .order_by(
            DiscoveredJob.ignored_at.desc()
        )
        .all()
    )

    return render_template(
        "ignored_discovered_jobs.html",
        jobs=jobs
    )


@app.route("/discovered-jobs/<int:job_id>/unsave", methods=["POST"],)
@login_required
def unsave_discovered_job(job_id):
    job = DiscoveredJob.query.filter_by(
        id=job_id,
        user_id=current_user.id,
    ).first_or_404()

    job.is_saved = False
    job.saved_at = None

    db.session.commit()

    return discovered_job_action_response(
        job=job,
        action="unsave",
        message=(
            "Job removed from saved jobs."
        ),
    )


@app.route("/discovered-jobs/<int:job_id>/ignore", methods=["POST"],)
@login_required
def ignore_discovered_job(job_id):
    job = DiscoveredJob.query.filter_by(
        id=job_id,
        user_id=current_user.id,
    ).first_or_404()

    job.is_ignored = True
    job.is_saved = False
    job.ignored_at = datetime.now(
        timezone.utc
    )
    job.saved_at = None

    db.session.commit()

    message = (
        f"{job.position_title} "
        f"was removed from your results."
    )

    return discovered_job_action_response(
        job=job,
        action="ignore",
        message=message,
    )


@app.route("/discovered-jobs/<int:job_id>/restore", methods=["POST"])
@login_required
def restore_discovered_job(job_id):
    job = DiscoveredJob.query.filter_by(
        id=job_id,
        user_id=current_user.id
    ).first_or_404()

    job.is_ignored = False
    job.ignored_at = None

    db.session.commit()

    flash("Job restored to your discovered jobs.", "success")

    return redirect(
        request.referrer or url_for("ignored_discovered_jobs")
    )


def job_bazaar_search_terms(search_term):
    normalized = str(
        search_term or ""
    ).strip()

    if not normalized:
        return []

    aliases = {
        "it": (
            "IT support",
            "IT specialist",
            "IT technician",
            "information technology",
            "help desk",
            "service desk",
            "desktop support",
            "technical support",
            "systems administrator",
            "system administrator",
            "support engineer",
        ),
        "help desk": (
            "help desk",
            "service desk",
            "desktop support",
            "technical support",
            "IT support",
            "IT specialist",
            "IT technician",
        ),
        "service desk": (
            "service desk",
            "help desk",
            "desktop support",
            "technical support",
            "IT support",
        ),
    }

    alias_terms = aliases.get(
        normalized.casefold()
    )

    if alias_terms is not None:
        return list(dict.fromkeys(alias_terms))

    return [normalized]


def selected_integer_ids(field_name="job_ids"):
    selected = set()

    for raw_value in request.form.getlist(field_name):
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            continue

        if value > 0:
            selected.add(value)

    return sorted(selected)


def cached_source_payload(cached_job):
    payload = cached_job.job_payload

    if isinstance(payload, dict):
        return dict(payload)

    return {}


def get_or_create_user_job_from_cache(cached_job):
    payload = cached_source_payload(cached_job)

    posting_url = canonical_job_posting_url(
        cached_job.posting_url
        or payload.get("posting_url")
    )

    if not posting_url:
        raise ValueError(
            "This shared job does not have a usable posting URL."
        )

    company_name = str(
        cached_job.company_name
        or payload.get("company_name")
        or "Unknown Company"
    ).strip()

    position_title = str(
        cached_job.position_title
        or payload.get("position_title")
        or "Untitled Position"
    ).strip()

    location = str(
        payload.get("location")
        or ""
    ).strip()

    fingerprint = build_job_fingerprint(
        company_name,
        position_title,
        location,
        posting_url,
    )

    discovered_job = (
        DiscoveredJob.query
        .filter_by(
            user_id=current_user.id,
            fingerprint=fingerprint,
        )
        .first()
    )

    if discovered_job is None:
        posting_url_variants = {
            posting_url,
            f"{posting_url}/",
        }

        discovered_job = (
            DiscoveredJob.query
            .filter(
                DiscoveredJob.user_id == current_user.id,
                DiscoveredJob.posting_url.in_(posting_url_variants),
            )
            .first()
        )

    if discovered_job is not None:
        return discovered_job

    source_name = str(
        payload.get("source")
        or cached_job.source_name
        or "Unknown"
    ).strip()

    employment_type = str(
        payload.get("employment_type")
        or ""
    ).strip()

    salary = str(
        payload.get("salary")
        or ""
    ).strip()

    visa_sponsorship = str(
        payload.get("visa_sponsorship")
        or "Unknown"
    ).strip()

    apply_url = canonical_job_posting_url(
        payload.get("apply_url")
        or posting_url
    )

    discovered_job = DiscoveredJob(
        user_id=current_user.id,
        search_profile_id=None,
        source=source_name[:80],
        external_id=(
            str(
                payload.get("external_id")
                or cached_job.external_id
                or ""
            )[:255]
            or None
        ),
        company_name=company_name[:150],
        position_title=position_title[:150],
        location=location[:150] or None,
        employment_type=employment_type[:50] or None,
        salary=salary[:100] or None,
        visa_sponsorship=visa_sponsorship[:20] or "Unknown",
        posting_url=posting_url[:1000],
        apply_url=(
            apply_url[:1000]
            if apply_url
            else posting_url[:1000]
        ),
        recruiter_name=(
            str(payload.get("recruiter_name") or "")[:150]
            or None
        ),
        recruiter_email=(
            str(payload.get("recruiter_email") or "")[:255]
            or None
        ),
        recruiter_contact_url=(
            str(payload.get("recruiter_contact_url") or "")[:1000]
            or None
        ),
        recruiter_contact_source=(
            str(payload.get("recruiter_contact_source") or "")[:100]
            or None
        ),
        job_description=payload.get("job_description") or None,
        fingerprint=fingerprint,
    )

    db.session.add(discovered_job)

    return discovered_job


def job_bazaar_view(cached_job, user_state_by_url):
    payload = cached_source_payload(cached_job)

    posting_url = canonical_job_posting_url(
        cached_job.posting_url
    )

    user_state = user_state_by_url.get(
        posting_url
    )

    return {
        "id": cached_job.id,
        "source": (
            payload.get("source")
            or cached_job.source_name
        ),
        "company_name": cached_job.company_name,
        "position_title": cached_job.position_title,
        "location": payload.get("location"),
        "workplace_type": payload.get("workplace_type"),
        "employment_type": payload.get("employment_type"),
        "salary": payload.get("salary"),
        "posting_url": cached_job.posting_url,
        "apply_url": (
            payload.get("apply_url")
            or cached_job.posting_url
        ),
        "published_at": cached_job.published_at,
        "first_seen_at": cached_job.first_seen_at,
        "expires_at": cached_job.expires_at,
        "is_saved": bool(
            user_state
            and user_state.is_saved
        ),
        "is_ignored": bool(
            user_state
            and user_state.is_ignored
        ),
        "discovered_job_id": (
            user_state.id
            if user_state
            else None
        ),
    }


@app.route("/jobs")
@login_required
def job_bazaar():
    page = request.args.get("page", 1, type=int)
    search_term = request.args.get("q", "").strip()
    location_filter = request.args.get("location", "").strip()
    workplace_filter = (
        request.args.get("workplace", "")
        .strip()
        .lower()
    )
    employment_filter = (
        request.args.get("employment", "")
        .strip()
        .lower()
    )
    source_filter = request.args.get("source", "").strip()
    sort_order = (
        request.args.get("sort", "newest")
        .strip()
        .lower()
    )

    if workplace_filter not in {
        "",
        "remote",
        "hybrid",
        "on-site",
    }:
        workplace_filter = ""

    if employment_filter not in {
        "",
        "full-time",
        "part-time",
        "internship",
        "contract",
        "temporary",
        "freelance",
    }:
        employment_filter = ""

    if sort_order not in {
        "newest",
        "company",
        "title",
        "expiring",
    }:
        sort_order = "newest"

    now = datetime.now(timezone.utc)

    ignored_job_exists = db.exists().where(
        db.and_(
            DiscoveredJob.user_id == current_user.id,
            DiscoveredJob.is_ignored.is_(True),
            db.func.rtrim(
                DiscoveredJob.posting_url,
                "/",
            )
            == db.func.rtrim(
                CachedSourceJob.posting_url,
                "/",
            ),
        )
    )

    query = (
        CachedSourceJob.query
        .filter(
            CachedSourceJob.expires_at > now,
            ~ignored_job_exists,
        )
    )

    payload_text = db.cast(
        CachedSourceJob.job_payload,
        db.Text,
    )

    if search_term:
        search_clauses = []

        for expanded_term in job_bazaar_search_terms(
            search_term
        ):
            search_pattern = f"%{expanded_term}%"

            search_clauses.extend([
                CachedSourceJob.position_title.ilike(
                    search_pattern
                ),
                CachedSourceJob.company_name.ilike(
                    search_pattern
                ),
                payload_text.ilike(
                    search_pattern
                ),
            ])

        if search_clauses:
            query = query.filter(
                db.or_(*search_clauses)
            )

    if location_filter:
        query = query.filter(
            (
                CachedSourceJob
                .job_payload["location"]
                .as_string()
            ).ilike(
                f"%{location_filter}%"
            )
        )

    if workplace_filter:
        query = query.filter(
            db.func.lower(
                CachedSourceJob
                .job_payload["workplace_type"]
                .as_string()
            )
            == workplace_filter
        )

    if employment_filter:
        query = query.filter(
            db.func.lower(
                CachedSourceJob
                .job_payload["employment_type"]
                .as_string()
            )
            == employment_filter
        )

    if source_filter:
        source_pattern = f"%{source_filter}%"

        query = query.filter(
            db.or_(
                CachedSourceJob.source_name.ilike(
                    source_pattern
                ),
                (
                    CachedSourceJob
                    .job_payload["source"]
                    .as_string()
                ).ilike(
                    source_pattern
                ),
            )
        )

    effective_posted_at = db.func.coalesce(
        CachedSourceJob.published_at,
        CachedSourceJob.first_seen_at,
    )

    if sort_order == "company":
        query = query.order_by(
            CachedSourceJob.company_name.asc(),
            effective_posted_at.desc(),
        )
    elif sort_order == "title":
        query = query.order_by(
            CachedSourceJob.position_title.asc(),
            effective_posted_at.desc(),
        )
    elif sort_order == "expiring":
        query = query.order_by(
            CachedSourceJob.expires_at.asc(),
            effective_posted_at.desc(),
        )
    else:
        query = query.order_by(
            effective_posted_at.desc(),
            CachedSourceJob.id.desc(),
        )

    pagination = query.paginate(
        page=page,
        per_page=30,
        error_out=False,
    )

    cached_jobs = pagination.items

    page_urls = {
        canonical_job_posting_url(
            cached_job.posting_url
        )
        for cached_job in cached_jobs
        if canonical_job_posting_url(
            cached_job.posting_url
        )
    }

    url_variants = set()

    for posting_url in page_urls:
        url_variants.add(posting_url)
        url_variants.add(f"{posting_url}/")

    user_state_by_url = {}

    if url_variants:
        user_jobs = (
            DiscoveredJob.query
            .filter(
                DiscoveredJob.user_id == current_user.id,
                DiscoveredJob.posting_url.in_(
                    url_variants
                ),
            )
            .all()
        )

        for user_job in user_jobs:
            canonical_url = canonical_job_posting_url(
                user_job.posting_url
            )

            if canonical_url:
                user_state_by_url[
                    canonical_url
                ] = user_job

    jobs = [
        job_bazaar_view(
            cached_job,
            user_state_by_url,
        )
        for cached_job in cached_jobs
    ]

    return render_template(
        "job_bazaar.html",
        jobs=jobs,
        pagination=pagination,
        filters={
            "q": search_term,
            "location": location_filter,
            "workplace": workplace_filter,
            "employment": employment_filter,
            "source": source_filter,
            "sort": sort_order,
        },
    )


@app.route(
    "/jobs/<int:cached_job_id>/save",
    methods=["POST"],
)
@login_required
def save_job_bazaar_job(cached_job_id):
    cached_job = (
        CachedSourceJob.query
        .filter(
            CachedSourceJob.id == cached_job_id,
            CachedSourceJob.expires_at
            > datetime.now(timezone.utc),
        )
        .first_or_404()
    )

    try:
        job = get_or_create_user_job_from_cache(
            cached_job
        )

        job.is_saved = True
        job.is_ignored = False
        job.saved_at = datetime.now(timezone.utc)
        job.ignored_at = None

        db.session.commit()

        log_action(
            current_user.id,
            (
                "Saved Job Bazaar listing: "
                f"{job.company_name} - "
                f"{job.position_title}"
            ),
        )

        message = "Job saved to your account."

        if request.headers.get(
            "X-Requested-With"
        ) == "XMLHttpRequest":
            return jsonify({
                "success": True,
                "action": "save",
                "cached_job_id": cached_job.id,
                "discovered_job_id": job.id,
                "message": message,
            })

        flash(message, "success")
    except Exception as error:
        db.session.rollback()
        print(
            "JOB BAZAAR SAVE ERROR:",
            repr(error),
        )
        message = (
            "The Job Bazaar listing could not be saved."
        )

        if request.headers.get(
            "X-Requested-With"
        ) == "XMLHttpRequest":
            return jsonify({
                "success": False,
                "action": "save",
                "cached_job_id": cached_job.id,
                "message": message,
            }), 500

        flash(message, "danger")

    return redirect(
        request.referrer
        or url_for("job_bazaar")
    )


@app.route(
    "/jobs/<int:cached_job_id>/ignore",
    methods=["POST"],
)
@login_required
def ignore_job_bazaar_job(cached_job_id):
    cached_job = (
        CachedSourceJob.query
        .filter(
            CachedSourceJob.id == cached_job_id,
            CachedSourceJob.expires_at
            > datetime.now(timezone.utc),
        )
        .first_or_404()
    )

    try:
        job = get_or_create_user_job_from_cache(
            cached_job
        )

        job.is_ignored = True
        job.is_saved = False
        job.ignored_at = datetime.now(timezone.utc)
        job.saved_at = None

        db.session.commit()

        log_action(
            current_user.id,
            (
                "Ignored Job Bazaar listing: "
                f"{job.company_name} - "
                f"{job.position_title}"
            ),
        )

        message = "Job ignored for your account."

        if request.headers.get(
            "X-Requested-With"
        ) == "XMLHttpRequest":
            return jsonify({
                "success": True,
                "action": "ignore",
                "cached_job_id": cached_job.id,
                "discovered_job_id": job.id,
                "message": message,
            })

        flash(message, "info")
    except Exception as error:
        db.session.rollback()
        print(
            "JOB BAZAAR IGNORE ERROR:",
            repr(error),
        )
        message = (
            "The Job Bazaar listing could not be ignored."
        )

        if request.headers.get(
            "X-Requested-With"
        ) == "XMLHttpRequest":
            return jsonify({
                "success": False,
                "action": "ignore",
                "cached_job_id": cached_job.id,
                "message": message,
            }), 500

        flash(message, "danger")

    return redirect(
        request.referrer
        or url_for("job_bazaar")
    )


@app.route(
    "/jobs/bulk-ignore",
    methods=["POST"],
)
@login_required
def bulk_ignore_job_bazaar():
    selected_ids = selected_integer_ids()

    if not selected_ids:
        flash(
            "Select at least one Job Bazaar listing first.",
            "warning",
        )
        return redirect(
            request.referrer
            or url_for("job_bazaar")
        )

    cached_jobs = (
        CachedSourceJob.query
        .filter(
            CachedSourceJob.id.in_(selected_ids),
            CachedSourceJob.expires_at
            > datetime.now(timezone.utc),
        )
        .all()
    )

    ignored_count = 0

    try:
        now = datetime.now(timezone.utc)

        for cached_job in cached_jobs:
            job = get_or_create_user_job_from_cache(
                cached_job
            )

            job.is_ignored = True
            job.is_saved = False
            job.ignored_at = now
            job.saved_at = None
            ignored_count += 1

        db.session.commit()

        log_action(
            current_user.id,
            (
                "Bulk ignored "
                f"{ignored_count} "
                "Job Bazaar listings"
            ),
        )

        flash(
            f"{ignored_count} Job Bazaar listing(s) ignored.",
            "info",
        )
    except Exception as error:
        db.session.rollback()
        print(
            "JOB BAZAAR BULK IGNORE ERROR:",
            repr(error),
        )
        flash(
            "The selected Job Bazaar listings could not be ignored.",
            "danger",
        )

    return redirect(
        request.referrer
        or url_for("job_bazaar")
    )


@app.route(
    "/discovered-jobs/bulk",
    methods=["POST"],
)
@login_required
def bulk_discovered_jobs():
    action = (
        request.form.get("action", "")
        .strip()
        .lower()
    )

    if action not in {
        "ignore",
        "restore",
        "delete",
    }:
        flash(
            "Choose a valid bulk job action.",
            "warning",
        )
        return redirect(
            request.referrer
            or url_for("discovered_jobs")
        )

    selected_ids = selected_integer_ids()

    if not selected_ids:
        flash(
            "Select at least one job first.",
            "warning",
        )
        return redirect(
            request.referrer
            or url_for("discovered_jobs")
        )

    jobs = (
        DiscoveredJob.query
        .filter(
            DiscoveredJob.user_id
            == current_user.id,
            DiscoveredJob.id.in_(
                selected_ids
            ),
        )
        .all()
    )

    changed_count = 0
    now = datetime.now(timezone.utc)

    try:
        for job in jobs:
            if action == "ignore":
                job.is_ignored = True
                job.is_saved = False
                job.ignored_at = now
                job.saved_at = None
            elif action == "restore":
                job.is_ignored = False
                job.ignored_at = None
            else:
                db.session.delete(job)

            changed_count += 1

        db.session.commit()

        log_action(
            current_user.id,
            (
                f"Bulk {action} action on "
                f"{changed_count} discovered jobs"
            ),
        )
    except Exception as error:
        db.session.rollback()
        print(
            "DISCOVERED JOB BULK ACTION ERROR:",
            repr(error),
        )
        flash(
            "The selected jobs could not be updated.",
            "danger",
        )
        return redirect(
            request.referrer
            or url_for("discovered_jobs")
        )

    action_message = {
        "ignore": "ignored",
        "restore": "restored",
        "delete": "deleted",
    }[action]

    flash(
        (
            f"{changed_count} selected "
            f"job(s) {action_message}."
        ),
        (
            "success"
            if action == "restore"
            else "info"
        ),
    )

    return redirect(
        request.referrer
        or url_for("discovered_jobs")
    )

@app.route("/job-match", methods=["GET", "POST"])
@login_required
def job_match():
    form = JobMatchForm()

    latest_resume = get_latest_resume_for_user(current_user.id)
    
    application_id = request.args.get("application_id", type=int)
    application = None

    if application_id:
        application = JobApplication.query.filter_by(
            id=application_id,
            user_id=current_user.id
        ).first_or_404()

    match_score = None
    matched_keywords = []
    missing_keywords = []
    priority_gaps = []
    suggestions = []

    if not latest_resume or not latest_resume.extracted_text:
        flash("Upload a resume before matching jobs.", "warning")
        return redirect(url_for("upload_resume"))

    if request.method == "GET" and application:
        form.job_description.data = application.job_description or "" 

    if form.validate_on_submit():
        result = analyze_resume_job_match(
            latest_resume.extracted_text,
            form.job_description.data
        )

        match_score, matched_keywords, missing_keywords, priority_gaps, suggestions = result

        priority_gap_lines = []

        for gap in priority_gaps:
            category = gap.get("category", "Other")
            missing = ", ".join(gap.get("missing", []))
            priority_gap_lines.append(f"- {category}: {missing}")

        report_content = (
            f"Job Match Score: {match_score}/100\n\n"
            "Matched Keywords:\n"
            + (
                "\n".join(f"- {keyword}" for keyword in matched_keywords)
                if matched_keywords
                else "- None detected"
            )
            + "\n\nMissing Keywords:\n"
            + (
                "\n".join(f"- {keyword}" for keyword in missing_keywords)
                if missing_keywords
                else "- None detected"
            )
            + "\n\nPriority Gaps:\n"
            + (
                "\n".join(priority_gap_lines)
                if priority_gap_lines
                else "- No major priority gaps detected"
            )
            + "\n\nSuggestions:\n"
            + (
                "\n".join(f"- {suggestion}" for suggestion in suggestions)
                if suggestions
                else "- No additional suggestions"
            )
        )

        report = AIReport(
            user_id=current_user.id,
            report_type="job_match",
            company=application.company_name if application else None,
            position=application.position_title if application else None,
            content=report_content
        )

        db.session.add(report)
        db.session.commit()

        log_action(
            current_user.id,
            f"Saved job match report with score {match_score}/100"
        )

    return render_template(
        "job_match.html",
        form=form,
        latest_resume=latest_resume,
        application=application,
        match_score=match_score,
        matched_keywords=matched_keywords,
        missing_keywords=missing_keywords,
        priority_gaps=priority_gaps,
        suggestions=suggestions
    )


@app.route("/interview-prep/<int:prep_id>")
@login_required
def view_interview_prep(prep_id):
    prep = InterviewPrep.query.get_or_404(prep_id)

    if prep.user_id != current_user.id:
        flash("You are not authorized to view this interview prep.", "danger")
        return redirect(url_for("dashboard"))

    behavioral_questions = json.loads(prep.behavioral_questions)
    technical_questions = json.loads(prep.technical_questions)
    study_topics = json.loads(prep.study_topics)

    return render_template(
        "view_interview_prep.html",
        prep=prep,
        behavioral_questions=behavioral_questions,
        technical_questions=technical_questions,
        study_topics=study_topics
    )


@app.route("/applications/<int:application_id>")
@login_required
def view_application(application_id):
    application = JobApplication.query.get_or_404(application_id)

    if application.user_id != current_user.id:
        flash("You are not authorized to view this application.", "danger")
        return redirect(url_for("dashboard"))

    decrypted_notes = decrypt_text(application.notes)

    return render_template(
        "view_application.html",
        application=application,
        decrypted_notes=decrypted_notes
    )


@app.route("/job-descriptions/new", methods=["GET", "POST"])
@login_required
def save_job_description():
    form = SavedJobDescriptionForm()

    if form.validate_on_submit():
        saved_job = SavedJobDescription(
            company=form.company.data,
            role=form.role.data,
            description=form.description.data,
            user_id=current_user.id
        )

        db.session.add(saved_job)
        db.session.commit()

        log_action(
            current_user.id,
            f"Saved job description for {form.company.data} - {form.role.data}"
        )

        flash("Job description saved successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template("save_job_description.html", form=form)


@app.route("/job-descriptions/<int:job_id>")
@login_required
def view_job_description(job_id):
    job = SavedJobDescription.query.get_or_404(job_id)

    if job.user_id != current_user.id:
        flash("You are not authorized to view this job description.", "danger")
        return redirect(url_for("dashboard"))

    return render_template("view_job_description.html", job=job)


@app.route("/job-descriptions/<int:job_id>/edit", methods=["GET", "POST"])
@login_required
def edit_job_description(job_id):
    job = SavedJobDescription.query.get_or_404(job_id)

    if job.user_id != current_user.id:
        flash("You are not authorized to edit this job description.", "danger")
        return redirect(url_for("dashboard"))

    form = SavedJobDescriptionForm()

    if form.validate_on_submit():
        job.company = form.company.data
        job.role = form.role.data
        job.description = form.description.data

        db.session.commit()

        log_action(
            current_user.id,
            f"Updated saved job description for {job.company} - {job.role}"
        )

        flash("Job description updated successfully.", "success")
        return redirect(url_for("view_job_description", job_id=job.id))

    elif request.method == "GET":
        form.company.data = job.company
        form.role.data = job.role
        form.description.data = job.description

    return render_template(
        "save_job_description.html",
        form=form,
        title="Edit Job Description"
    )


@app.route("/job-descriptions/<int:job_id>/delete", methods=["POST"])
@login_required
def delete_job_description(job_id):
    job = SavedJobDescription.query.get_or_404(job_id)

    if job.user_id != current_user.id:
        flash("You are not authorized to delete this job description.", "danger")
        return redirect(url_for("dashboard"))

    company = job.company
    role = job.role

    db.session.delete(job)

    log_action(
        current_user.id,
        f"Deleted saved job description for {company} - {role}"
    )

    flash("Job description deleted successfully.", "info")
    return redirect(url_for("dashboard"))


start_scheduler(app)

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
