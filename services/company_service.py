
def analyze_company(company_name):
    score = 100

    strengths = []
    warnings = []

    company = company_name.lower()

    trusted_companies = [
        "amazon",
        "google",
        "microsoft",
        "apple",
        "meta",
        "netflix",
        "ibm",
        "oracle",
        "deloitte",
        "accenture"
    ]

    suspicious_keywords = [
        "crypto",
        "investment",
        "forex",
        "gift card",
        "mlm"
    ]

    if company in trusted_companies:
        strengths.append("Established company recognized in industry.")
    else:
        score -= 20
        warnings.append(
            "Company is not currently in the trusted company database."
        )

    for keyword in suspicious_keywords:
        if keyword in company:
            score -= 20
            warnings.append(
                f"Company name contains potentially suspicious keyword: {keyword}"
            )

    if len(company_name) < 3:
        score -= 20
        warnings.append("Company name appears unusually short.")

    if score >= 80:
        risk_level = "Low Risk"
    elif score >= 50:
        risk_level = "Medium Risk"
    else:
        risk_level = "High Risk"

    if not strengths:
        strengths.append(
            "Additional research is recommended before applying."
        )

    return score, risk_level, strengths, warnings
