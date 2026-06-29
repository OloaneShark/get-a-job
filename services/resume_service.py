
def analyze_resume_text(text):
    score = 100
    feedback = []

    resume_text = text.lower()

    checks = {
        "contact information": ["email", "phone", "linkedin", "github"],
        "skills section": ["skills", "technical skills"],
        "experience section": ["experience", "work experience"],
        "projects section": ["projects", "project"],
        "education section": ["education", "degree", "university", "college"],
        "certifications": ["certification", "certifications", "comptia", "security+", "aws"],
        "cloud/devops keywords": ["aws", "docker", "ci/cd", "github actions", "linux"],
        "security keywords": ["security", "vulnerability", "encryption", "authentication", "audit"]
    }

    for section, keywords in checks.items():
        if not any(keyword in resume_text for keyword in keywords):
            score -= 10
            feedback.append(f"Missing or weak {section}.")

    if len(resume_text.split()) < 250:
        score -= 15
        feedback.append("Resume may be too short.")

    if len(resume_text.split()) > 1200:
        score -= 10
        feedback.append("Resume may be too long.")

    strong_action_words = [
        "built", "implemented", "developed", "deployed",
        "configured", "secured", "automated", "designed"
    ]

    if not any(word in resume_text for word in strong_action_words):
        score -= 10
        feedback.append("Add stronger action verbs like built, deployed, secured, or automated.")

    score = max(score, 0)

    if not feedback:
        feedback.append("Resume looks strong based on the current rule-based checks.")

    return score, feedback