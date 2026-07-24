
#Implemented AI on July 2nd, 2026 at 8:27 pm est
#THIS WAS A HEADACHE TO GET WORKING
#Implemented feature for failing AI connection for AI features on July 5th, 2026
#THIS TOOK ME 2 DAYS TO GET WORKING PROPERLY WITHOUT MESSING UP AAAAAHHHHHHH

import os
import bcrypt
import json
import csv
from dotenv import load_dotenv
from io import StringIO
from werkzeug.utils import secure_filename
from flask import Flask, render_template, redirect, url_for, flash, request, Response, send_from_directory
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
from services.scheduler_service import start_scheduler
from services.job_sources.source_utils import (
    extract_ashby_job_board_name,
    extract_greenhouse_board_token,
    extract_lever_company_slug
)
from services.job_sources.discovery.source_discovery import (detect_source_type)
from services.job_sources.discovery.validation_service import (validate_source_candidate)

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

        added_count = 0
        skipped_count = 0
        failed_count = 0

        for url in urls:
            try:
                source_type, source_identifier = (
                    detect_source_type(url)
                )

                existing_source = JobSourceCompany.query.filter_by(
                    source_type=source_type,
                    source_identifier=source_identifier
                ).first()

                if existing_source:
                    skipped_count += 1
                    continue

                candidate = JobSourceCandidate.query.filter_by(
                    source_type=source_type,
                    source_identifier=source_identifier
                ).first()

                if candidate is None:
                    candidate = JobSourceCandidate(
                        company_name=source_identifier,
                        source_type=source_type,
                        source_identifier=source_identifier,
                        discovered_url=url,
                        discovery_method="admin_bulk_import",
                        validation_status="pending"
                    )

                    db.session.add(candidate)
                    db.session.flush()

                    added_count += 1
                else:
                    skipped_count += 1

                validate_source_candidate(candidate)

            except Exception as error:
                failed_count += 1
                print(
                    f"SOURCE DISCOVERY FAILED | "
                    f"URL: {url} | Error: {error}"
                )

        db.session.commit()

        flash(
            f"Discovery complete: {added_count} added, "
            f"{skipped_count} skipped, "
            f"{failed_count} failed.",
            "success"
        )

        return redirect(
            url_for("job_source_candidates")
        )

    candidates = (
        JobSourceCandidate.query
        .order_by(JobSourceCandidate.discovered_at.desc())
        .all()
    )

    return render_template(
        "job_source_candidates.html",
        form=form,
        candidates=candidates
    )


@app.route("/admin/job-source-candidates/<int:candidate_id>/approve", methods=["POST"])
@login_required
def approve_job_source_candidate(candidate_id):
    if not current_user.is_admin:
        flash("Administrator access is required.", "danger")
        return redirect(url_for("dashboard"))

    candidate = JobSourceCandidate.query.get_or_404(
        candidate_id
    )

    if candidate.validation_status != "valid":
        flash(
            "Only validated sources can be approved.",
            "warning"
        )
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

        flash(
            "That source already exists and was marked approved.",
            "info"
        )

        return redirect(
            url_for("job_source_candidates")
        )

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

    flash(
        f"{source.company_name} was approved and activated.",
        "success"
    )

    return redirect(
        url_for("job_source_candidates")
    )


@app.route("/admin/job-source-candidates/approve-all-valid", methods=["POST"])
@login_required
def approve_all_valid_job_sources():
    if not current_user.is_admin:
        flash("Administrator access is required.", "danger")
        return redirect(url_for("dashboard"))

    candidates = JobSourceCandidate.query.filter_by(
        validation_status="valid"
    ).all()

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

    flash(
        f"{approved_count} sources approved. "
        f"{skipped_count} already existed.",
        "success"
    )

    return redirect(
        url_for("job_source_candidates")
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
    if not current_user.is_admin:
        flash("Administrator access is required.", "danger")
        return redirect(url_for("dashboard"))

    candidate = JobSourceCandidate.query.get_or_404(
        candidate_id
    )

    candidate.validation_status = "rejected"

    db.session.commit()

    flash("Source candidate rejected.", "info")

    return redirect(
        url_for("job_source_candidates")
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
        application.location = form.location.data,
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
        profile = JobSearchProfile(
            user_id=current_user.id,
            name=form.name.data,
            keywords=form.keywords.data,
            locations=form.locations.data,
            employment_types=form.employment_types.data,
            remote_only=form.remote_only.data,
            visa_required=form.visa_required.data,
            minimum_salary=form.minimum_salary.data,
            active=form.active.data
        )

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

    if form.validate_on_submit():
        profile.name = form.name.data
        profile.keywords = form.keywords.data
        profile.locations = form.locations.data
        profile.employment_types = form.employment_types.data
        profile.remote_only = form.remote_only.data
        profile.visa_required = form.visa_required.data
        profile.minimum_salary = form.minimum_salary.data
        profile.active = form.active.data

        db.session.commit()

        log_action(
            current_user.id,
            f"Updated search profile '{profile.name}'"
        )

        flash("Search profile updated successfully.", "success")
        return redirect(url_for("search_profiles"))

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


@app.route("/discovered-jobs")
@login_required
def discovered_jobs():
    jobs = (
        DiscoveredJob.query
        .filter_by(user_id=current_user.id)
        .order_by(DiscoveredJob.discovered_at.desc())
        .all()
    )

    return render_template(
        "discovered_jobs.html",
        jobs=jobs
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


if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    start_scheduler(app)

    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
