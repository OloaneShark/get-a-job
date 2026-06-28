
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from forms import RegistrationForm, LoginForm, JobApplicationForm
from models import db, User, JobApplication
import bcrypt

app = Flask(__name__)

app.config["SECRET_KEY"] = "super-secret-key"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///site.db"

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
        application = JobApplication(
            company_name=form.company_name.data,
            position_title=form.position_title.data,
            status=form.status.data,
            salary=form.salary.data,
            visa_sponsorship=form.visa_sponsorship.data,
            notes=form.notes.data,
            user_id=current_user.id
        )

        db.session.add(application)
        db.session.commit()

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
        application.company_name = form.company_name.data
        application.position_title = form.position_title.data
        application.status = form.status.data
        application.salary = form.salary.data
        application.visa_sponsorship = form.visa_sponsorship.data
        application.notes = form.notes.data

        db.session.commit()

        flash("Application updated successfully.", "success")
        return redirect(url_for("dashboard"))

    elif request.method == "GET":
        form.company_name.data = application.company_name
        form.position_title.data = application.position_title
        form.status.data = application.status
        form.salary.data = application.salary
        form.visa_sponsorship.data = application.visa_sponsorship
        form.notes.data = application.notes

    return render_template("add_application.html", form=form, title="Edit Application")


@app.route("/applications/<int:application_id>/delete", methods=["POST"])
@login_required
def delete_application(application_id):
    application = JobApplication.query.get_or_404(application_id)

    if application.user_id != current_user.id:
        flash("You are not authorized to delete this application.", "danger")
        return redirect(url_for("dashboard"))

    db.session.delete(application)
    db.session.commit()

    flash("Application deleted successfully.", "info")
    return redirect(url_for("dashboard"))


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)