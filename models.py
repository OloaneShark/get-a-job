
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    
    username = db.Column( db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    
    last_ip = db.Column(db.String(45), nullable=True)
    
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    
    plan = db.Column(db.String(20), default="free", nullable=False)
    
    ai_usage = db.relationship("AIUsage", backref="user", lazy=True, cascade="all, delete-orphan")
    
    security_events = db.relationship("AccountSecurityEvent", backref="user", lazy=True, cascade="all, delete-orphan")
    
    applications = db.relationship("JobApplication", backref="owner", lazy=True)
    audit_logs = db.relationship("AuditLog", backref="user", lazy=True)
    resumes = db.relationship("Resume", backref="owner", lazy=True)
    interview_preps = db.relationship("InterviewPrep", backref="owner", lazy=True)
    saved_job_descriptions = db.relationship("SavedJobDescription", backref="owner", lazy=True)
    
    job_search_profiles = db.relationship("JobSearchProfile", backref="owner", lazy=True, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User {self.username}>"
    
    
class JobApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    
    company_name = db.Column(db.String(100), nullable=False)
    position_title = db.Column(db.String(100), nullable=False)
    
    company_website = db.Column(db.String(255))
    job_posting_url = db.Column(db.String(255))
    job_description = db.Column(db.Text)
    recruiter_email = db.Column(db.String(120))
    
    legitimacy_score = db.Column(db.Integer, default=0)
    risk_level = db.Column(db.String(50), default="Unknown")
    
    status = db.Column(db.String(50), nullable=False, default="Applied")
    salary = db.Column(db.String(50))
    location = db.Column(db.String(100))
    visa_sponsorship = db.Column(db.String(20), default="Unknown")
    application_date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    
    follow_up_date = db.Column(db.DateTime)
    last_contacted_date = db.Column(db.DateTime)
    
    history = db.relationship("ApplicationHistory",backref="application", lazy=True, cascade="all, delete-orphan")
    
    company_intelligence = db.relationship("CompanyIntelligence", backref="application", uselist=False, cascade="all, delete-orphan")
    
    
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
    

class CompanyIntelligence(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_name = db.Column(db.String(150), nullable=False)

    industry = db.Column(db.String(150))
    headquarters = db.Column(db.String(150))
    company_size = db.Column(db.String(100))
    work_style = db.Column(db.String(100))
    visa_summary = db.Column(db.String(255))

    tech_stack = db.Column(db.Text)
    positive_signals = db.Column(db.Text)
    risk_signals = db.Column(db.Text)
    interview_topics = db.Column(db.Text)
    summary = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    application_id = db.Column(
        db.Integer,
        db.ForeignKey("job_application.id"),
        nullable=False,
        unique=True
    )
    
    
class AIUsage(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    feature = db.Column(db.String(50), nullable=False)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )
    
    
class AccountSecurityEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    event_type = db.Column(
        db.String(50),
        nullable=False
    )

    ip_hash = db.Column(
        db.String(64),
        nullable=False,
        index=True
    )

    device_hash = db.Column(
        db.String(64),
        index=True
    )

    user_agent_hash = db.Column(
        db.String(64),
        index=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )
    
    
class DiscoveredJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    source = db.Column(db.String(80), nullable=False)
    external_id = db.Column(db.String(255))
    company_name = db.Column(db.String(150), nullable=False)
    position_title = db.Column(db.String(150), nullable=False)
    location = db.Column(db.String(150))
    employment_type = db.Column(db.String(50))
    salary = db.Column(db.String(100))
    visa_sponsorship = db.Column(db.String(20), default="Unknown")

    posting_url = db.Column(db.String(1000), nullable=False)
    apply_url = db.Column(db.String(1000))
    job_description = db.Column(db.Text)

    fingerprint = db.Column(
        db.String(64),
        nullable=False,
        index=True
    )

    discovered_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "fingerprint",
            name="uq_user_discovered_job"
        ),
    )
    
    
class ApplicationPackage(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    status = db.Column(
        db.String(50),
        default="Prepared",
        nullable=False
    )

    resume_id = db.Column(
        db.Integer,
        db.ForeignKey("resume.id"),
        nullable=False
    )

    cover_letter_text = db.Column(db.Text)
    answers_json = db.Column(db.Text)

    confirmation_reference = db.Column(db.String(255))
    confirmation_url = db.Column(db.String(1000))
    failure_reason = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    submitted_at = db.Column(db.DateTime)

    application_id = db.Column(
        db.Integer,
        db.ForeignKey("job_application.id"),
        nullable=False
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )
    
    
class JobSearchProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    keywords = db.Column(db.Text, nullable=False)
    locations = db.Column(db.Text, nullable=False)
    employment_types = db.Column(db.Text, nullable=True)
    remote_only = db.Column(db.Boolean, default=False, nullable=False)
    visa_required = db.Column(db.Boolean, default=False, nullable=False)
    minimum_salary = db.Column(db.Integer, nullable=True)
    search_frequency = db.Column(db.String(20), default="hourly", nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_searched_at = db.Column(db.DateTime, nullable=True)
    last_result_count = db.Column(db.Integer, default=0, nullable=False)
    last_search_status = db.Column(db.String(30), default="Never Run", nullable=False)
    last_search_error = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<JobSearchProfile {self.name}>"
    
    
