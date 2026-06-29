
import re


def analyze_resume_text(text):
    score = 100
    feedback = []

    resume_text = text.lower()
    words = resume_text.split()

    checks = {
        "contact information": ["email", "@", "phone", "github", "portfolio"],
        "skills section": ["skills", "technical skills"],
        "experience section": ["experience", "work experience"],
        "projects section": ["projects", "project"],
        "education section": ["education", "degree", "university", "college"],
        "certifications": ["certification", "certifications", "comptia", "security+", "aws"],
        "cloud/devops keywords": ["aws", "docker", "ci/cd", "github actions", "linux", "postgresql"],
        "security keywords": ["security", "vulnerability", "encryption", "authentication", "audit", "iam"]
    }

    for section, keywords in checks.items():
        if not any(keyword in resume_text for keyword in keywords):
            score -= 8
            feedback.append(f"Missing or weak {section}.")

    measurable_results = re.findall(r"\d+%|\$\d+|\d+\+", text)

    if len(measurable_results) < 3:
        score -= 15
        feedback.append("Add more measurable results, such as percentages, dollar amounts, counts, or numbers.")

    strong_action_words = [
        "built", "implemented", "developed", "deployed",
        "configured", "secured", "automated", "designed",
        "created", "optimized", "managed", "integrated"
    ]

    action_word_count = sum(1 for word in strong_action_words if word in resume_text)

    if action_word_count < 5:
        score -= 10
        feedback.append("Use more strong action verbs like built, deployed, automated, secured, and implemented.")

    weak_phrases = [
        "responsible for",
        "helped with",
        "worked on",
        "assisted with",
        "familiar with"
    ]

    found_weak_phrases = [phrase for phrase in weak_phrases if phrase in resume_text]

    if found_weak_phrases:
        score -= 10
        feedback.append(f"Replace weak phrases: {', '.join(found_weak_phrases)}.")

    if "github" not in resume_text:
        score -= 8
        feedback.append("Add a GitHub link so employers can view your projects.")

    if "linkedin" not in resume_text:
        score -= 5
        feedback.append("Consider adding LinkedIn if available, but GitHub/portfolio matters more for technical roles.")

    if len(words) < 300:
        score -= 10
        feedback.append("Resume may be too short. Add more project detail or impact.")

    if len(words) > 900:
        score -= 8
        feedback.append("Resume may be too long. Consider tightening it.")

    score = max(score, 0)

    if score >= 85:
        rating = "Strong"
    elif score >= 70:
        rating = "Good"
    elif score >= 50:
        rating = "Needs Work"
    else:
        rating = "Weak"

    if not feedback:
        feedback.append("Resume looks strong based on the current rule-based checks.")

    return score, rating, feedback