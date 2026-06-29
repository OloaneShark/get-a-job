
import re


def analyze_resume_text(text):
    score = 100

    strengths = []
    improvements = []

    resume_text = text.lower()
    words = resume_text.split()

    checks = {
        "Contact Information": ["email", "@", "phone", "github", "portfolio"],
        "Skills Section": ["skills", "technical skills"],
        "Experience Section": ["experience", "work experience"],
        "Projects Section": ["projects", "project"],
        "Education Section": ["education", "degree", "university", "college"],
        "Certifications": ["certification", "certifications", "comptia", "security+", "aws"],
        "Cloud/DevOps Keywords": ["aws", "docker", "ci/cd", "github actions", "linux", "postgresql"],
        "Security Keywords": ["security", "vulnerability", "encryption", "authentication", "audit", "iam"]
    }

    for section, keywords in checks.items():
        if any(keyword in resume_text for keyword in keywords):
            strengths.append(f"{section} detected.")
        else:
            score -= 8
            improvements.append(f"Missing or weak {section}.")

    measurable_results = re.findall(r"\d+%|\$\d+|\d+\+", text)

    if len(measurable_results) >= 3:
        strengths.append("Good use of measurable achievements.")
    else:
        score -= 15
        improvements.append(
            "Add more measurable results such as percentages, dollar amounts, or counts."
        )

    strong_action_words = [
        "built", "implemented", "developed", "deployed",
        "configured", "secured", "automated", "designed",
        "created", "optimized", "managed", "integrated"
    ]

    action_word_count = sum(
        1 for word in strong_action_words
        if word in resume_text
    )

    if action_word_count >= 5:
        strengths.append("Strong action verbs detected.")
    else:
        score -= 10
        improvements.append(
            "Use more strong action verbs like built, deployed, automated, secured, and implemented."
        )

    weak_phrases = [
        "responsible for",
        "helped with",
        "worked on",
        "assisted with",
        "familiar with"
    ]

    found_weak_phrases = [
        phrase for phrase in weak_phrases
        if phrase in resume_text
    ]

    if found_weak_phrases:
        score -= 10
        improvements.append(
            f"Replace weak phrases: {', '.join(found_weak_phrases)}."
        )

    if "github" in resume_text:
        strengths.append("GitHub presence detected.")
    else:
        score -= 8
        improvements.append(
            "Add a GitHub link so employers can view your projects."
        )

    if "linkedin" not in resume_text:
        score -= 5
        improvements.append(
            "Consider adding LinkedIn if available."
        )

    if len(words) < 300:
        score -= 10
        improvements.append(
            "Resume may be too short. Add more project detail or impact."
        )

    if len(words) > 900:
        score -= 8
        improvements.append(
            "Resume may be too long. Consider tightening it."
        )

    score = max(score, 0)

    if score >= 85:
        rating = "Strong"
    elif score >= 70:
        rating = "Good"
    elif score >= 50:
        rating = "Needs Work"
    else:
        rating = "Weak"

    return score, rating, strengths, improvements