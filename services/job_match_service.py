
import re


def extract_keywords(text):
    text = text.lower()

    keyword_categories = {
        "Programming": [
            "python", "javascript", "html", "css", "react",
            "flask", "django", "api", "rest"
        ],
        "Databases": [
            "sql", "postgresql", "mysql", "sqlite"
        ],
        "Cloud": [
            "aws", "azure", "gcp", "iam", "s3", "ec2", "cloud"
        ],
        "DevOps": [
            "docker", "kubernetes", "linux", "git",
            "github actions", "ci/cd", "terraform"
        ],
        "Security": [
            "security", "encryption", "authentication",
            "authorization", "vulnerability", "owasp",
            "incident response", "logging", "monitoring"
        ]
    }

    found = {}

    for category, keywords in keyword_categories.items():
        found[category] = []

        for keyword in keywords:
            pattern = r"\b" + re.escape(keyword) + r"\b"

            if re.search(pattern, text):
                found[category].append(keyword)

    return found


def flatten_keywords(keyword_dict):
    keywords = []

    for category_keywords in keyword_dict.values():
        keywords.extend(category_keywords)

    return keywords


def analyze_resume_job_match(resume_text, job_description):
    resume_keywords_by_category = extract_keywords(resume_text)
    job_keywords_by_category = extract_keywords(job_description)

    resume_keywords = flatten_keywords(resume_keywords_by_category)
    job_keywords = flatten_keywords(job_keywords_by_category)

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

    priority_gaps = []

    for category, keywords in job_keywords_by_category.items():
        missing_in_category = [
            keyword for keyword in keywords
            if keyword not in resume_keywords
        ]

        if missing_in_category:
            priority_gaps.append({
                "category": category,
                "missing": missing_in_category
            })

    suggestions = []

    for gap in priority_gaps:
        suggestions.append(
            f"Strengthen your {gap['category']} section by adding truthful experience with: {', '.join(gap['missing'])}."
        )

    if not suggestions:
        suggestions.append(
            "Your resume appears to cover the major keywords found in this job description."
        )

    return (
        match_score,
        matched_keywords,
        missing_keywords,
        priority_gaps,
        suggestions
    )
    