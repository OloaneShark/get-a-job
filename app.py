
import os
import bcrypt
from werkzeug.utils import secure_filename
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from forms import RegistrationForm, LoginForm, JobApplicationForm, ResumeUploadForm, ResumeAnalysisForm
from services.resume_service import analyze_resume_text
from models import db, User, JobApplication, Resume
from utils.encryption import encrypt_text, decrypt_text
from services.legitimacy_service import calculate_legitimacy_score
from utils.audit_logger import log_action


app = Flask(__name__)

app.config["SECRET_KEY"] = "super-secret-key"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///site.db"
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
    return render_template("dashboard.html")


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
            user_id=current_user.id
        )

        db.session.add(application)
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


@app.route("/resumes/analyze", methods=["GET", "POST"])
@login_required
def analyze_resume():
    form = ResumeAnalysisForm()
    score = None
    feedback = None

    if form.validate_on_submit():
        score, feedback = analyze_resume_text(form.resume_text.data)

        log_action(current_user.id, f"Analyzed resume strength. Score: {score}/100")

    return render_template(
        "analyze_resume.html",
        form=form,
        score=score,
        feedback=feedback
    )


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)