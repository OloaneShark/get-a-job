
import re


def extract_keywords(text):
    text = text.lower()

    keywords = [
        "python", "flask", "django", "sql", "postgresql", "mysql",
        "aws", "azure", "gcp", "docker", "kubernetes", "linux",
        "git", "github actions", "ci/cd", "terraform",
        "security", "iam", "encryption", "authentication",
        "authorization", "vulnerability", "owasp", "api",
        "rest", "html", "css", "javascript", "react",
        "monitoring", "logging", "incident response"
    ]

    found = []

    for keyword in keywords:
        pattern = r"\b" + re.escape(keyword) + r"\b"
        if re.search(pattern, text):
            found.append(keyword)

    return found


def analyze_resume_job_match(resume_text, job_description):
    resume_keywords = extract_keywords(resume_text)
    job_keywords = extract_keywords(job_description)

    matched_keywords = [
        keyword for keyword in job_keywords
        if keyword in resume_keywords
    ]

    missing_keywords = [
        keyword for keyword in job_keywords
        if keyword not in resume_keywords
    ]

    if job_keywords:
        match_score = int((len(matched_keywords) / len(job_keywords)) * 100)
    else:
        match_score = 0

    suggestions = []

    for keyword in missing_keywords:
        suggestions.append(
            f"Consider adding relevant experience or project details related to {keyword}, if truthful."
        )

    if not suggestions:
        suggestions.append(
            "Your resume appears to cover the major keywords found in this job description."
        )

    return match_score, matched_keywords, missing_keywords, suggestions
