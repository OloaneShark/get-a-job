
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    
    username = db.Column( db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    applications = db.relationship("JobApplication", backref="owner", lazy=True)
    audit_logs = db.relationship("AuditLog", backref="user", lazy=True)
    resumes = db.relationship("Resume", backref="owner", lazy=True)
    interview_preps = db.relationship("InterviewPrep", backref="owner", lazy=True)
    saved_job_descriptions = db.relationship("SavedJobDescription", backref="owner", lazy=True)
    
    def __repr__(self):
        return f"<User {self.username}>"
    
    
class JobApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    
    company_name = db.Column(db.String(100), nullable=False)
    position_title = db.Column(db.String(100), nullable=False)
    
    company_website = db.Column(db.String(255))
    job_posting_url = db.Column(db.String(255))
    recruiter_email = db.Column(db.String(120))
    
    legitimacy_score = db.Column(db.Integer, default=0)
    risk_level = db.Column(db.String(50), default="Unknown")
    
    status = db.Column(db.String(50), nullable=False, default="Applied")
    salary = db.Column(db.String(50))
    visa_sponsorship = db.Column(db.String(20), default="Unknown")
    application_date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    
    follow_up_date = db.Column(db.DateTime)
    last_contacted_date = db.Column(db.DateTime)
    
    history = db.relationship("ApplicationHistory", backref="application", lazy=True, cascade="all, delete-orphan")
    
    
class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    action = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )
    
    
class Resume(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    version_name = db.Column(db.String(100))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    analysis_score = db.Column(db.Integer, default=0)
    analysis_feedback = db.Column(db.Text)

    extracted_text = db.Column(db.Text)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )


class InterviewPrep(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(100), nullable=False)

    behavioral_questions = db.Column(db.Text)
    technical_questions = db.Column(db.Text)
    study_topics = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    
    
class ApplicationHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    status = db.Column(db.String(50), nullable=False)
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    application_id = db.Column(
        db.Integer,
        db.ForeignKey("job_application.id"),
        nullable=False
    )
    
    
class SavedJobDescription(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )
    

class AIReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    report_type = db.Column(db.String(50), nullable=False)
    company = db.Column(db.String(120))
    position = db.Column(db.String(120))
    content = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )
    

