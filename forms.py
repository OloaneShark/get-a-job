
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, BooleanField, SelectField
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
    
    
