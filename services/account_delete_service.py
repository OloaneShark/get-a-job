
from models import (
    db,
    AIReport,
    AIUsage,
    AccountSecurityEvent,
    ApplicationPackage,
    AuditLog,
    CompanyIntelligence,
    DiscoveredJob,
    EmailVerificationCode,
    InterviewPrep,
    JobApplication,
    JobSearchProfile,
    Resume,
    SavedJobDescription,
    TwoFactorRecoveryCode,
)


def delete_user_account(user):
    user_id = user.id

    for model in (
        EmailVerificationCode,
        TwoFactorRecoveryCode,
        AIUsage,
        AccountSecurityEvent,
        AIReport,
        ApplicationPackage,
    ):
        model.query.filter_by(user_id=user_id).delete(
            synchronize_session=False
        )

    CompanyIntelligence.query.filter_by(user_id=user_id).delete(
        synchronize_session=False
    )

    for job in DiscoveredJob.query.filter_by(user_id=user_id).all():
        db.session.delete(job)
    db.session.flush()

    for profile in JobSearchProfile.query.filter_by(user_id=user_id).all():
        db.session.delete(profile)

    for application in JobApplication.query.filter_by(user_id=user_id).all():
        db.session.delete(application)
    db.session.flush()

    for model in (
        Resume,
        InterviewPrep,
        SavedJobDescription,
        AuditLog,
    ):
        model.query.filter_by(user_id=user_id).delete(
            synchronize_session=False
        )

    db.session.delete(user)
