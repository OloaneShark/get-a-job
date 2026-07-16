
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
from models import db, User, JobApplication, AuditLog, Resume, InterviewPrep, ApplicationHistory, SavedJobDescription, AIReport, CompanyIntelligence
from utils.encryption import encrypt_text, decrypt_text
from services.legitimacy_service import calculate_legitimacy_score
from utils.audit_logger import log_action
from services.interview_service import generate_interview_prep
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
    JobUrlImportForm
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


load_dotenv()


app = Flask(__name__)
csrf = CSRFProtect(app)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
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
            password=hashed_password
        )
        
        db.session.add(user)
        db.session.commit()
        
        flash("Account successfully created! You can now log in.", "success")
        return redirect(url_for("home"))
    
    return render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        
        if user and bcrypt.checkpw(
            form.password.data.encode("utf-8"),
            user.password.encode("utf-8")
        ):
            login_user(user)
            log_action(user.id, "User logged in")
            flash("Login successful.", "success")
            return redirect(url_for("dashboard"))
        
        flash("Login failed. Check your email and passowrd again.", "danger")
        
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
    application = JobApplication.query.get_or_404(application_id)

    if application.user_id != current_user.id:
        flash("You are not authorized to view this application.", "danger")
        return redirect(url_for("dashboard"))

    related_reports = (
        AIReport.query
        .filter_by(user_id=current_user.id)
        .filter(
            db.or_(
                AIReport.company.ilike(application.company_name),
                AIReport.position.ilike(application.position_title)
            )
        )
        .order_by(AIReport.created_at.desc())
        .all()
    )

    return render_template(
        "application_detail.html",
        application=application,
        related_reports=related_reports
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

    ai_feedback = None
    manual_prompt = None

    if not latest_resume or not latest_resume.extracted_text:
        flash("Upload a resume before running an AI resume review.", "warning")
        return redirect(url_for("upload_resume"))

    if form.validate_on_submit():
        try:
            ai_feedback = analyze_resume(
                latest_resume.extracted_text,
                form.job_description.data
            )

            report = AIReport(
                user_id=current_user.id,
                report_type="resume_review",
                company=None,
                position=None,
                content=ai_feedback
            )

            db.session.add(report)
            db.session.commit()

            log_action(current_user.id, "Ran AI resume review")

        except Exception as e:
            manual_prompt = build_resume_review_prompt(
                latest_resume.extracted_text,
                form.job_description.data
            )

            flash(
                "The AI API is currently unavailable. Copy the prompt below into ChatGPT.",
                "warning"
            )

            print(e)

    return render_template(
        "ai_resume_review.html",
        form=form,
        ai_feedback=ai_feedback,
        manual_prompt=manual_prompt,
        latest_resume=latest_resume
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
        flash("Upload a resume before generating a cover letter.", "warning")
        return redirect(url_for("upload_resume"))

    if request.method == "GET" and application:
        form.company.data = application.company_name
        form.position.data = application.position_title
        form.job_description.data = application.job_description or ""

    if form.validate_on_submit():
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
                company=form.company.data,
                position=form.position.data,
                content=cover_letter
            )

            db.session.add(report)
            db.session.commit()

            log_action(
                current_user.id,
                f"Generated AI cover letter for "
                f"{form.company.data} - {form.position.data}"
            )

        except Exception as e:
            manual_prompt = build_cover_letter_prompt(
                form.company.data,
                form.position.data,
                latest_resume.extracted_text,
                form.job_description.data
            )

            flash(
                "The AI API is currently unavailable. Copy the prompt below into ChatGPT.",
                "warning"
            )

            print(e)

    return render_template(
        "ai_cover_letter.html",
        form=form,
        cover_letter=cover_letter,
        manual_prompt=manual_prompt,
        latest_resume=latest_resume
    )


@app.route("/applications/<int:application_id>/ai/cover-letter", methods=["GET", "POST"])
@login_required
def application_ai_cover_letter(application_id):
    application = JobApplication.query.get_or_404(application_id)

    if application.user_id != current_user.id:
        flash("You are not authorized to access this application.", "danger")
        return redirect(url_for("dashboard"))

    form = AICoverLetterForm()

    latest_resume = get_latest_resume_for_user(current_user.id)

    cover_letter = None
    manual_prompt = None

    if request.method == "GET":
        form.company.data = application.company_name
        form.position.data = application.position_title
        form.job_description.data = (
            decrypt_text(application.notes)
            if application.notes
            else ""
        )

    if not latest_resume or not latest_resume.extracted_text:
        flash("Upload a resume before generating a cover letter.", "warning")
        return redirect(url_for("upload_resume"))

    if form.validate_on_submit():
        try:
            cover_letter = generate_cover_letter(
                form.company.data,
                form.position.data,
                latest_resume.extracted_text,
                form.job_description.data
            )

            log_action(
                current_user.id,
                f"Generated AI cover letter for {application.company_name}"
            )

        except Exception as e:
            manual_prompt = build_cover_letter_prompt(
                form.company.data,
                form.position.data,
                latest_resume.extracted_text,
                form.job_description.data
            )

            flash(
                "The AI API is currently unavailable. Copy the prompt below into ChatGPT.",
                "warning"
            )

            print(e)

    return render_template(
        "ai_cover_letter.html",
        form=form,
        cover_letter=cover_letter,
        manual_prompt=manual_prompt,
        latest_resume=latest_resume
    )


@app.route("/applications/<int:application_id>/ai/resume-review", methods=["GET", "POST"])
@login_required
def application_ai_resume_review(application_id):
    application = JobApplication.query.get_or_404(application_id)

    if application.user_id != current_user.id:
        flash("You are not authorized to access this application.", "danger")
        return redirect(url_for("dashboard"))

    form = AIResumeReviewForm()

    ai_feedback = None
    manual_prompt = None
    latest_resume = get_latest_resume_for_user(current_user.id)

    if request.method == "GET":
        form.job_description.data = (
            decrypt_text(application.notes)
            if application.notes
            else ""
        )

    if form.validate_on_submit():
        if not latest_resume or not latest_resume.extracted_text:
            flash("Upload a resume before running AI resume review.", "warning")
            return redirect(url_for("upload_resume"))

        try:
            ai_feedback = analyze_resume(
                latest_resume.extracted_text,
                form.job_description.data
            )

            log_action(
                current_user.id,
                f"Generated AI resume review for {application.company_name}"
            )

        except Exception as e:
            manual_prompt = build_resume_review_prompt(
                latest_resume.extracted_text,
                form.job_description.data
            )

            flash(
                "The AI API is currently unavailable. Copy the prompt below into ChatGPT.",
                "warning"
            )

            print(e)

    return render_template(
        "ai_resume_review.html",
        form=form,
        ai_feedback=ai_feedback,
        manual_prompt=manual_prompt,
        latest_resume=latest_resume
    )


@app.route("/interview-prep", methods=["GET", "POST"])
@login_required
def interview_prep():
    form = InterviewPrepForm()

    behavioral_questions = None
    technical_questions = None
    study_topics = None

    if form.validate_on_submit():
        behavioral_questions, technical_questions, study_topics = (
            generate_interview_prep(
                form.company.data,
                form.role.data
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

        log_action(current_user.id, f"Saved interview prep for {form.company.data} - {form.role.data}")

        log_action(current_user.id, f"Generated interview prep for {form.company.data}")

    return render_template(
        "interview_prep.html",
        form=form,
        behavioral_questions=behavioral_questions,
        technical_questions=technical_questions,
        study_topics=study_topics
    )


@app.route("/ai/interview-coach", methods=["GET", "POST"])
@login_required
def ai_interview_coach():
    form = AIInterviewCoachForm()
    latest_resume = get_latest_resume_for_user(current_user.id)
    
    interview_prep = None
    manual_prompt = None

    if not latest_resume or not latest_resume.extracted_text:
        flash("Upload a resume before generating interview prep.", "warning")
        return redirect(url_for("upload_resume"))
    
    if form.validate_on_submit():
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
                company=form.company.data,
                position=form.position.data,
                content=interview_prep
            )
            
            db.session.add(report)
            db.session.commit()

            log_action(current_user.id, f"Generated AI interview prep for {form.company.data} - {form.position.data}")

        except Exception as e:
            manual_prompt = build_interview_coach_prompt(
                form.company.data,
                form.position.data,
                form.job_description.data,
                latest_resume.extracted_text
            )

            flash(
                "The AI API is currently unavailable. Copy the prompt below into ChatGPT.",
                "warning"
            )

            print(e)

    return render_template(
        "ai_interview_coach.html",
        form=form,
        interview_prep=interview_prep,
        manual_prompt=manual_prompt,
        latest_resume=latest_resume
    )


@app.route("/applications/<int:application_id>/ai/interview-coach", methods=["GET", "POST"])
@login_required
def application_ai_interview_coach(application_id):
    application = JobApplication.query.get_or_404(application_id)

    if application.user_id != current_user.id:
        flash("You are not authorized.", "danger")
        return redirect(url_for("dashboard"))

    form = AIInterviewCoachForm()
    latest_resume = get_latest_resume_for_user(current_user.id)

    interview_prep = None
    manual_prompt = None

    if request.method == "GET":
        form.company.data = application.company_name
        form.position.data = application.position_title
        form.job_description.data = (
            decrypt_text(application.notes)
            if application.notes
            else ""
        )

    if not latest_resume or not latest_resume.extracted_text:
        flash("Upload a resume before generating interview prep.", "warning")
        return redirect(url_for("upload_resume"))

    if form.validate_on_submit():
        try:
            interview_prep = generate_interview_coach(
                form.company.data,
                form.position.data,
                form.job_description.data,
                latest_resume.extracted_text
            )

            log_action(
                current_user.id,
                f"Generated AI interview prep for {application.company_name}"
            )

        except Exception as e:
            manual_prompt = build_interview_coach_prompt(
                form.company.data,
                form.position.data,
                form.job_description.data,
                latest_resume.extracted_text
            )

            flash(
                "The AI API is currently unavailable. Copy the prompt below into ChatGPT.",
                "warning"
            )

            print(e)

    return render_template(
        "ai_interview_coach.html",
        form=form,
        interview_prep=interview_prep,
        manual_prompt=manual_prompt,
        latest_resume=latest_resume
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


@app.route("/job-match", methods=["GET", "POST"])
@login_required
def job_match():
    form = JobMatchForm()

    latest_resume = get_latest_resume_for_user(current_user.id)

    match_score = None
    matched_keywords = []
    missing_keywords = []
    priority_gaps = []
    suggestions = []

    if not latest_resume or not latest_resume.extracted_text:
        flash("Upload a resume before matching jobs.", "warning")
        return redirect(url_for("upload_resume"))

    print("POST?", request.method)
    print("Form errors:", form.errors)   

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
            company=None,
            position=None,
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


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
