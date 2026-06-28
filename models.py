
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
    visa_sponsorship = db.Column(db.Boolean, default=False)
    application_date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    
    
class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    action = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )