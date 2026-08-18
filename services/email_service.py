
import os

import boto3


def send_verification_email(recipient_email, code):
    backend = os.getenv(
        "EMAIL_BACKEND",
        "console"
    ).strip().lower()

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

    if backend != "ses":
        raise RuntimeError(
            "EMAIL_BACKEND must be either 'console' or 'ses'."
        )

    sender = os.getenv(
        "EMAIL_FROM",
        "security@jobfinitum.com"
    ).strip()

    region = os.getenv(
        "AWS_SES_REGION",
        os.getenv("AWS_REGION", "us-east-1")
    ).strip()

    client = boto3.client(
        "sesv2",
        region_name=region
    )

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

    client.send_email(
        FromEmailAddress=sender,
        Destination={
            "ToAddresses": [recipient_email]
        },
        Content={
            "Simple": {
                "Subject": {
                    "Data": subject,
                    "Charset": "UTF-8"
                },
                "Body": {
                    "Text": {
                        "Data": text_body,
                        "Charset": "UTF-8"
                    },
                    "Html": {
                        "Data": html_body,
                        "Charset": "UTF-8"
                    }
                }
            }
        }
    )
