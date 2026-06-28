
def calculate_legitimacy_score(company_website, job_posting_url, recruiter_email, salary, notes):
    score = 100
    red_flags = []

    scam_keywords = [
        "gift card",
        "western union",
        "crypto",
        "telegram",
        "whatsapp only",
        "pay for equipment",
        "send money",
        "ssn",
        "bank account"
    ]

    if not company_website:
        score -= 20
        red_flags.append("Missing company website.")

    if not job_posting_url:
        score -= 15
        red_flags.append("Missing job posting URL.")

    if recruiter_email and company_website:
        website_domain = company_website.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
        email_domain = recruiter_email.split("@")[-1]

        if website_domain not in email_domain:
            score -= 25
            red_flags.append("Recruiter email does not appear to match company domain.")

    if salary:
        salary_text = salary.lower()
        if "200k" in salary_text or "$200,000" in salary_text or "300k" in salary_text:
            score -= 15
            red_flags.append("Salary may be unusually high.")

    combined_text = f"{notes or ''}".lower()

    for keyword in scam_keywords:
        if keyword in combined_text:
            score -= 20
            red_flags.append(f"Suspicious keyword found: {keyword}")

    score = max(score, 0)

    if score >= 80:
        risk_level = "Low Risk"
    elif score >= 50:
        risk_level = "Medium Risk"
    else:
        risk_level = "High Risk"

    return score, risk_level, red_flags