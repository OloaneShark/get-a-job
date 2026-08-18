
from flask_wtf.file import FileField, FileAllowed
from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    PasswordField,
    SubmitField,
    TextAreaField,
    BooleanField,
    SelectField,
    IntegerField,
    DateField,
    EmailField,
    FloatField,
    HiddenField,
    RadioField,
    SelectMultipleField,
    widgets
)
from wtforms.validators import (
    DataRequired,
    Length,
    Email,
    EqualTo,
    URL,
    Optional,
    ValidationError
)


class MultiCheckboxField(SelectMultipleField):
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()


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
        validators=[
            DataRequired(),
            Length(min=10, max=128)
        ]
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
    
    
class EmailVerificationForm(FlaskForm):
    code = StringField(
        "Verification code",
        validators=[
            DataRequired(),
            Length(min=6, max=6)
        ]
    )
    submit = SubmitField("Verify Email")


class ResendVerificationForm(FlaskForm):
    submit = SubmitField("Send New Code")


class ProfileSettingsForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            DataRequired(),
            Length(min=3, max=20)
        ]
    )

    profile_picture = FileField(
        "Profile Picture",
        validators=[
            FileAllowed(
                ["jpg", "jpeg", "png", "webp"],
                "Upload a JPG, PNG, or WebP image."
            )
        ]
    )

    submit = SubmitField("Save Profile")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField(
        "Current Password",
        validators=[Optional()]
    )

    new_password = PasswordField(
        "New Password",
        validators=[
            DataRequired(),
            Length(min=10, max=128)
        ]
    )

    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[
            DataRequired(),
            EqualTo("new_password")
        ]
    )

    submit = SubmitField("Update Password")


class TwoFactorSetupForm(FlaskForm):
    code = StringField(
        "6-digit code",
        validators=[
            DataRequired(),
            Length(min=6, max=6)
        ]
    )
    submit = SubmitField("Enable Two-Step Verification")


class TwoFactorChallengeForm(FlaskForm):
    code = StringField(
        "Authenticator or recovery code",
        validators=[
            DataRequired(),
            Length(min=6, max=32)
        ]
    )
    submit = SubmitField("Verify")


class DisableTwoFactorForm(FlaskForm):
    code = StringField(
        "Authenticator or recovery code",
        validators=[
            DataRequired(),
            Length(min=6, max=32)
        ]
    )
    password = PasswordField(
        "Password",
        validators=[Optional()]
    )
    submit = SubmitField("Disable Two-Step Verification")


class DeleteAccountForm(FlaskForm):
    confirmation = StringField(
        'Type "DELETE" to confirm',
        validators=[DataRequired()]
    )
    password = PasswordField(
        "Password",
        validators=[Optional()]
    )
    two_factor_code = StringField(
        "Authenticator or recovery code",
        validators=[Optional()]
    )
    submit = SubmitField("Delete My Account")


class JobApplicationForm(FlaskForm):
    company_name = StringField("Company Name", validators=[DataRequired()])
    position_title = StringField("Position Title", validators=[DataRequired()])
    
    company_website = StringField("Company Website")
    job_posting_url = StringField("Job Posting URL")
    job_description = TextAreaField(
        "Job Description",
        validators=[Optional()],
        render_kw={
            "rows": 10,
            "placeholder": "Paste the complete job description here..."
        }
    )
    recruiter_email = StringField("Recruiter Email")
    follow_up_date = DateField(
        "Follow-Up Date",
        format="%Y-%m-%d",
        validators=[Optional()],
    )
    last_contacted_date = DateField(
        "Last Contacted Date",
        format="%Y-%m-%d",
        validators=[Optional()],
    )
    
    status = SelectField(
        "Status",
        choices=[
            ("Applied", "Applied"),
            ("HR Screen", "HR Screen"),
            ("Technical Interview", "Technical Interview"),
            ("Manager Interview", "Manager Interview"),
            ("Final Interview", "Final Interview"),
            ("Offer Received", "Offer Received"),
            ("Accepted", "Accepted"),
            ("Rejected", "Rejected"),
            ("Withdrawn", "Withdrawn")
        ],
        validators=[DataRequired()]
    )
    
    salary = StringField("Salary")
    location = StringField(
        "Location",
        validators=[
            Optional(),
            Length(max=100),
        ],
    )
    visa_sponsorship = RadioField(
        "Visa Sponsorship",
        choices=[
            ("Unknown", "Unknown"),
            ("Yes", "Yes"),
            ("No", "No")
        ],
        default="Unknown"
    )
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

    job_description = TextAreaField(
        "Job Description",
        validators=[Optional()],
        render_kw={
            "rows": 10,
            "placeholder": "Paste the job description..."
        }
    )

    submit = SubmitField("Generate Interview Prep")
    

class CompanyLookupForm(FlaskForm):
    company_name = StringField(
        "Company Name",
        validators=[DataRequired()]
    )

    submit = SubmitField("Analyze Company")
    
    
class JobMatchForm(FlaskForm):
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
    job_description = TextAreaField(
        "Job Description",
        validators=[Optional()]
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
    job_description = TextAreaField("Job Description", validators=[DataRequired()])
    submit = SubmitField("Generate Interview Prep")
    
    
class JobUrlImportForm(FlaskForm):
    job_url = StringField(
        "Job Posting URL",
        validators=[DataRequired()]
    )

    company_name = StringField("Company")
    position_title = StringField("Position")

    salary = StringField("Salary")

    visa_sponsorship = SelectField(
        "Visa Sponsorship",
        choices=[
            ("Unknown", "Unknown"),
            ("Yes", "Yes"),
            ("No", "No")
        ],
        default="Unknown"
    )

    location = StringField("Location")

    job_description = TextAreaField("Job Description")

    import_submit = SubmitField("Import Job Posting")
    save_submit = SubmitField("Save as Application")


class JobSearchProfileForm(FlaskForm):
    name = StringField(
        "Profile Name",
        validators=[DataRequired()]
    )

    keywords = TextAreaField(
        "Keywords",
        validators=[DataRequired()]
    )

    experience_levels = MultiCheckboxField(
        "Experience Levels",
        choices=[
            ("intern", "Intern"),
            ("entry", "Entry Level"),
            ("junior", "Junior"),
            ("mid", "Mid Level"),
            ("senior", "Senior"),
            ("staff", "Staff"),
            ("principal", "Principal"),
            ("lead", "Lead"),
            ("manager", "Manager"),
            ("unspecified", "Unspecified"),
        ]
    )

    locations = TextAreaField(
        "Locations",
        validators=[DataRequired()]
    )

    workplace_types = MultiCheckboxField(
        "Workplace Types",
        choices=[
            ("remote", "Remote"),
            ("hybrid", "Hybrid"),
            ("on-site", "On-site"),
        ],
        default=["remote"]
    )

    remote_scope = SelectField(
        "Remote Location Scope",
        choices=[
            (
                "any",
                "Use the selected locations",
            ),
            (
                "worldwide",
                "Remote worldwide",
            ),
            (
                "selected_locations",
                "Remote in selected locations only",
            ),
        ],
        default="any",
        validators=[DataRequired()]
    )

    employment_types = StringField(
        "Employment Types"
    )

    visa_preference = SelectField(
        "Visa Sponsorship",
        choices=[
            ("any", "Any"),
            ("yes", "Yes"),
            ("no", "No"),
            ("unknown", "Unknown"),
        ],
        default="any",
        validators=[DataRequired()]
    )

    overseas_applicant_preference = SelectField(
        "Overseas Applicant Eligibility",
        choices=[
            ("any", "Any / not applicable"),
            ("yes", "Open to overseas applicants"),
            ("no", "Current residents only"),
            ("unknown", "Not stated"),
        ],
        default="any",
        validators=[DataRequired()]
    )

    maximum_posting_age_days = SelectField(
        "Maximum Posting Age",
        choices=[
            ("30", "1 month"),
            ("90", "3 months"),
            ("183", "6 months"),
            ("395", "13 months"),
        ],
        default="395",
        validators=[DataRequired()]
    )

    minimum_salary = IntegerField(
        "Minimum Salary",
        validators=[Optional()]
    )

    active = BooleanField(
        "Active",
        default=True
    )

    submit = SubmitField(
        "Save Search Profile"
    )

    def validate_workplace_types(
        self,
        workplace_types,
    ):
        if not workplace_types.data:
            raise ValidationError(
                "Select at least one workplace type."
            )
    
    
class JobSourceCompanyForm(FlaskForm):
    company_name = StringField("Company Name", validators=[DataRequired()])
    source_type = SelectField(
        "Source",
        choices=[
            ("greenhouse", "Greenhouse"),
            ("lever", "Lever"),
            ("ashby", "Ashby"),
            ("workday", "Workday"),
            ("bamboohr", "BambooHR"),
            ("workable", "Workable")
        ],
        validators=[DataRequired()]
    )
    
    source_identifier = StringField(
        "Careers URL or Board Token",
        validators=[DataRequired()]
    )
    
    careers_url = StringField("Company Careers URL")
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save Job Source")
    
    
class JobSourceDiscoveryForm(FlaskForm):
    source_urls = TextAreaField(
        "Company job-board URLs",
        validators=[DataRequired()],
        render_kw={
            "rows": 10,
            "placeholder": (
                "Paste one URL per line:\n"
                "https://jobs.lever.co/mujininc\n"
                "https://boards.greenhouse.io/remotecom\n"
                "https://jobs.ashbyhq.com/example\n"
                "https://nvidia.wd5.myworkdayjobs.com/"
                "NVIDIAExternalCareerSite\n"
                "https://soundstripe.bamboohr.com/careers\n"
                "https://apply.workable.com/falcomm/"
            )
        }
    )

    submit = SubmitField("Discover Sources")
