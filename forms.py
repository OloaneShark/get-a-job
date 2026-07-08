
from flask_wtf.file import FileField, FileAllowed
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField, SelectField, TextAreaField, DateField
from wtforms.validators import DataRequired, Length, Email, EqualTo


class RegistrationForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            DataRequired(),
            Length(min=3, max=20)
        ]
    )
    
    email = StringField(
        "Email",
        validators=[
            DataRequired(),
            Email()
        ]
    )
    
    password = PasswordField(
        "Password",
        validators=[DataRequired()]
    )
    
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[
            DataRequired(),
            EqualTo("password")
        ]
    )
    
    submit = SubmitField("Sign Up")
    
    
class LoginForm(FlaskForm):
    email=StringField(
        "Email",
        validators=[
            DataRequired(),
            Email()
        ]
    )
    
    password = PasswordField(
        "Password",
        validators=[DataRequired()]
    )
    
    submit = SubmitField("Login")
    
    
class JobApplicationForm(FlaskForm):
    company_name = StringField("Company Name", validators=[DataRequired()])
    position_title = StringField("Position Title", validators=[DataRequired()])
    
    company_website = StringField("Company Website")
    job_posting_url = StringField("Job Posting URL")
    recruiter_email = StringField("Recruiter Email")
    follow_up_date = DateField("Follow-Up Date", format="%Y-%m-%d")
    last_contacted_date = DateField("Last Contacted Date", format="%Y-%m-%d")
    
    status = SelectField(
        "Status",
        choices=[
            ("Applied", "Applied"),
            ("Interview Scheduled", "Interview Scheduled"),
            ("Rejected", "Rejected"),
            ("Offer Received", "Offer Received"),
            ("Accepted", "Accepted")
        ],
        validators=[DataRequired()]
    )
    
    salary = StringField("Salary")
    visa_sponsorship = BooleanField("Visa Sponsorship Available")
    notes = TextAreaField("Notes")
    
    submit = SubmitField("Save Application")
    
    
class ResumeUploadForm(FlaskForm):
    version_name = StringField("Version Name", validators=[DataRequired()])

    resume_file = FileField(
        "Resume File",
        validators=[
            DataRequired(),
            FileAllowed(["pdf", "doc", "docx"], "Only PDF, DOC, and DOCX files are allowed.")
        ]
    )

    submit = SubmitField("Upload Resume")
    
    
class ResumeAnalysisForm(FlaskForm):
    resume_text = TextAreaField(
        "Paste Resume Text",
        validators=[DataRequired()]
    )

    submit = SubmitField("Analyze Resume")
    
    
class InterviewPrepForm(FlaskForm):
    company = StringField(
        "Company Name",
        validators=[DataRequired()]
    )

    role = StringField(
        "Position Title",
        validators=[DataRequired()]
    )

    submit = SubmitField("Generate Interview Prep")
    

class CompanyLookupForm(FlaskForm):
    company_name = StringField(
        "Company Name",
        validators=[DataRequired()]
    )

    submit = SubmitField("Analyze Company")
    
    
class JobMatchForm(FlaskForm):
    resume_text = TextAreaField(
        "Paste Resume Text",
        validators=[DataRequired()]
    )

    job_description = TextAreaField(
        "Paste Job Description",
        validators=[DataRequired()]
    )

    submit = SubmitField("Analyze Match")
    
    
class SavedJobDescriptionForm(FlaskForm):
    company = StringField("Company", validators=[DataRequired()])
    role = StringField("Role", validators=[DataRequired()])
    description = TextAreaField("Job Description", validators=[DataRequired()])
    submit = SubmitField("Save Job Description")
    
    
class AIResumeReviewForm(FlaskForm):
    resume_text = TextAreaField("Resume Text")

    job_description = TextAreaField(
        "Optional Job Description"
    )

    submit = SubmitField("Run AI Resume Review")
    
    
class AICoverLetterForm(FlaskForm):
    company = StringField("Company", validators=[DataRequired()])
    position = StringField("Position", validators=[DataRequired()])
    
    resume_text = TextAreaField("Resume Text")
    
    job_description = TextAreaField(
        "Paste Job Description",
        validators=[DataRequired()]
    )
    
    submit = SubmitField("Generate Cover Letter")
    
    
class AIInterviewCoachForm(FlaskForm):
    company = StringField("Company", validators=[DataRequired()])
    position = StringField("Position", validators=[DataRequired()])
    job_description = StringField("Job Description", validators=[DataRequired()])
    submit = SubmitField("Generate Interview Prep")
    
    
class JobUrlImportForm(FlaskForm):
    job_url = StringField("Job Posting URL", validators=[DataRequired()])
    
    company_name = StringField("Company")
    position_title = StringField("Position")
    job_description = StringField("Job Description")
    
    import_submit = SubmitField("Import Job Posting")
    save_submit = SubmitField("Save as Application")
