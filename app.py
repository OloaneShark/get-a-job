
#Implemented AI on July 2nd, 2026 at 8:27 pm est
#THIS WAS A HEADACHE TO GET WORKING
#Implemented feature for failing AI connection for AI features on July 5th, 2026
#THIS TOOK ME 2 DAYS TO GET WORKING PROPERLY WITHOUT MESSING UP AAAAAHHHHHHH
#July 25, 2026 at 10:12 pm, I HATE TRYING TO GET THESE JOB BOARDS TO WORKS BECAUSE
#ASHBY AND LEVER AND GREENHOUSE ARE ANNOYING AND I HAVE TO PULL THEIR COMPANIES MANUALLY
#AAAAAAAAAAHHHHHHHHHHHHHH I HATE IT I HATE IT I HATE IT
#WHY CANT THEY BE NICE AND SIMPLE AND CLEAN LIKE REMOTE OK???

import os
import bcrypt
import json
import csv
from datetime import datetime, timezone
from dotenv import load_dotenv
from io import StringIO
from werkzeug.utils import secure_filename
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
    JobSourceCandidate
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
    JobSourceDiscoveryForm
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
from services.job_sources.workday_crawler import (
    WorkdayCrawler,
)
from services.job_sources.discovery.source_discovery import (detect_source_type)
from services.job_sources.discovery.validation_service import (validate_source_candidate)
from services.job_sources.discovery.candidate_service import (ingest_source_urls)
from services.job_sources.discovery.common_crawl_discovery import (run_common_crawl_discovery)

load_dotenv()


app = Flask(__name__)
csrf = CSRFProtect(app)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "pool_size": 3,
    "max_overflow": 2,
}
app.config["UPLOAD_FOLDER"] = "uploads"

if not app.config["SQLALCHEMY_DATABASE_URI"]:
    raise RuntimeError("DATABASE_URL is not set.")

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
    return User.query.get(int(user_id))


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
    form = RegistrationForm()

    if form.validate_on_submit():
        hashed_password = bcrypt.hashpw(
            form.password.data.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        user = User(
            username=form.username.data,
            email=form.email.data,
            password=hashed_password,
            last_ip=get_client_ip()
        )

        try:
            db.session.add(user)
            db.session.flush()

            record_security_event(user.id, "registration")

            db.session.commit()

            flash("Account successfully created! You can now log in.", "success")

            return redirect(url_for("home"))

        except Exception as e:
            db.session.rollback()

            print("REGISTRATION SECURITY EVENT ERROR:", repr(e))

            flash("The account could not be created. Please try again.", "danger")

    return render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()

    if form.validate_on_submit():
        user = User.query.filter_by(
            email=form.email.data
        ).first()

        if user and bcrypt.checkpw(
            form.password.data.encode("utf-8"),
            user.password.encode("utf-8")
        ):
            try:
                user.last_ip = get_client_ip()

                record_security_event(user.id, "login")

                db.session.commit()

                login_user(user)

                log_action(user.id, "User logged in")

                flash("Login successful.", "success")

                return redirect(url_for("dashboard"))

            except Exception as e:
                db.session.rollback()

                print("LOGIN SECURITY EVENT ERROR:", repr(e))

                flash("Login could not be completed. Please try again.", "danger")

                return render_template("login.html", form=form)

        flash("Login failed. Check your email and password again.", "danger")

    return render_template("login.html", form=form)


@app.route("/logout")
@login_required
def logout():
    logout_user()
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
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], stored_filename)

        file.save(file_path)

        extracted_text = extract_resume_text(file_path)

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

    if form.validate_on_submit():
        selected_workplace_types = (
            form.workplace_types.data
            or ["remote"]
        )

        profile = JobSearchProfile(
            user_id=current_user.id,
            name=form.name.data,
            keywords=form.keywords.data,
            locations=form.locations.data,
            employment_types=form.employment_types.data,
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
            )
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

        form.maximum_posting_age_days.data = str(
            profile.maximum_posting_age_days
            or 395
        )

    if form.validate_on_submit():
        selected_workplace_types = (
            form.workplace_types.data
            or ["remote"]
        )

        profile.name = form.name.data
        profile.keywords = form.keywords.data
        profile.locations = form.locations.data
        profile.employment_types = form.employment_types.data

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
        profile.active = form.active.data

        db.session.commit()

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
