import os

import boto3
import resend


def _build_verification_message(code):
    subject = "Your JobFinitum verification code"

    text_body = (
        "Verify your JobFinitum email address.\n\n"
        f"Your verification code is: {code}\n\n"
        "This code expires in 10 minutes. "
        "If you did not create or sign in to a "
        "JobFinitum account, you can ignore this email."
    )

    html_body = (
        '<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;">'
        '<h2>Verify your JobFinitum email</h2>'
        '<p>Use this verification code:</p>'
        '<div style="font-size:32px;font-weight:700;letter-spacing:8px;'
        'padding:18px;text-align:center;border:1px solid #ddd;border-radius:12px;">'
        + code
        + '</div>'
        '<p style="margin-top:20px;">This code expires in 10 minutes.</p>'
        '<p>If you did not create or sign in to a JobFinitum account, '
        'you can ignore this email.</p></div>'
    )

    return subject, text_body, html_body


def send_verification_email(recipient_email, code):
    backend = os.getenv("EMAIL_BACKEND", "console").strip().lower()
    subject, text_body, html_body = _build_verification_message(code)

    if backend == "console":
        print(
            "\n"
            "========================================\n"
            "JOBFINITUM EMAIL VERIFICATION\n"
            f"Recipient: {recipient_email}\n"
            f"Verification code: {code}\n"
            "========================================\n"
        )
        return

    sender = os.getenv(
        "EMAIL_FROM",
        "JobFinitum <security@mail.jobfinitum.com>"
    ).strip()

    if backend == "resend":
        api_key = os.getenv("RESEND_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("RESEND_API_KEY is not set.")

        resend.api_key = api_key
        result = resend.Emails.send({
            "from": sender,
            "to": [recipient_email],
            "subject": subject,
            "text": text_body,
            "html": html_body,
        })

        print(
            "RESEND VERIFICATION EMAIL SENT | "
            f"Recipient: {recipient_email} | "
            f"Result: {result}"
        )
        return

    if backend == "ses":
        region = os.getenv(
            "AWS_SES_REGION",
            os.getenv("AWS_REGION", "us-east-1")
        ).strip()

        client = boto3.client("sesv2", region_name=region)
        client.send_email(
            FromEmailAddress=sender,
            Destination={"ToAddresses": [recipient_email]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                }
            },
        )
        return

    raise RuntimeError(
        "EMAIL_BACKEND must be 'console', 'resend', or 'ses'."
    )
