
import os
import bcrypt
import json
import csv
from dotenv import load_dotenv
from io import StringIO
from werkzeug.utils import secure_filename
from flask import Flask, render_template, redirect, url_for, flash, request, Response, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from services.resume_service import analyze_resume_text
from models import db, User, JobApplication, Resume, InterviewPrep, ApplicationHistory, SavedJobDescription
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
    SavedJobDescriptionForm
)
from services.company_service import analyze_company
from services.job_match_service import analyze_resume_job_match


load_dotenv()


app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["UPLOAD_FOLDER"] = "uploads"

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


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
            visa_sponsorship=form.visa_sponsorship.data,
            notes=encrypt_text(form.notes.data),
            legitimacy_score=score,
            risk_level=risk_level,
            user_id=current_user.id,
            follow_up_date=form.follow_up_date.data,
            last_contacted_date=form.last_contacted_date.data
        )

        db.session.add(application)
        db.session.commit()

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

        score, risk_level, red_flags = calculate_legitimacy_score(
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
        application.recruiter_email = form.recruiter_email.data
        application.status = form.status.data
        application.salary = form.salary.data
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
        return redirect(url_for("dashboard"))

    elif request.method == "GET":
        form.company_name.data = application.company_name
        form.position_title.data = application.position_title
        form.company_website.data = application.company_website
        form.job_posting_url.data = application.job_posting_url
        form.recruiter_email.data = application.recruiter_email
        form.status.data = application.status
        form.salary.data = application.salary
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

        resume = Resume(
            filename=stored_filename,
            original_filename=original_filename,
            version_name=form.version_name.data,
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
def analyze_resume():
    form = ResumeAnalysisForm()
    score = None
    rating = None
    strengths = []
    improvements = []
    
    if form.validate_on_submit():
        score, rating, strengths, improvements = analyze_resume_text(form.resume_text.data)
        
        print("STRENGTHS:", strengths)
        print("IMPROVEMENTS:", improvements)

        log_action(current_user.id, f"Analyzed resume strength. Score: {score}/100 - {rating}")

    return render_template(
        "analyze_resume.html",
        form=form,
        score=score,
        rating=rating,
        strengths=strengths,
        improvements=improvements
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


@app.route("/job-match", methods=["GET", "POST"])
@login_required
def job_match():
    form = JobMatchForm()

    match_score = None
    matched_keywords = None
    missing_keywords = None
    suggestions = None
    priority_gaps = None
    
    if form.validate_on_submit():
        match_score, matched_keywords, missing_keywords, priority_gaps, suggestions = (
            analyze_resume_job_match(
                form.resume_text.data,
                form.job_description.data
            )
        )

        log_action(current_user.id, f"Analyzed resume/job match. Score: {match_score}/100")

    return render_template(
        "job_match.html",
        form=form,
        match_score=match_score,
        matched_keywords=matched_keywords,
        missing_keywords=missing_keywords,
        suggestions=suggestions,
        priority_gaps=priority_gaps,
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


if __name__ == "__main__":
    app.run(debug=True)