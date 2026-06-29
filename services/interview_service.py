
def generate_interview_prep(company, role):
    behavioral_questions = [
        "Tell me about yourself.",
        "Describe a time you faced a difficult challenge.",
        "Tell me about a conflict you had with a teammate.",
        "Describe a time you failed and what you learned.",
        "Tell me about a project you are most proud of."
    ]

    technical_questions = []
    study_topics = []

    role_text = role.lower()

    if "security" in role_text:
        technical_questions.extend([
            "What is the difference between authentication and authorization?",
            "Explain the CIA Triad.",
            "How would you secure a web application?",
            "What is least privilege?"
        ])

        study_topics.extend([
            "Authentication vs Authorization",
            "Web Security",
            "IAM",
            "Encryption",
            "OWASP Top 10"
        ])

    if "cloud" in role_text:
        technical_questions.extend([
            "What is AWS IAM?",
            "How do security groups differ from NACLs?",
            "Explain shared responsibility in AWS."
        ])

        study_topics.extend([
            "AWS IAM",
            "AWS Security Groups",
            "Cloud Security",
            "S3 Security"
        ])

    if "devops" in role_text:
        technical_questions.extend([
            "Explain a CI/CD pipeline.",
            "How would you secure a CI/CD pipeline?",
            "What is Docker and why is it used?"
        ])

        study_topics.extend([
            "Docker",
            "CI/CD",
            "GitHub Actions",
            "Pipeline Security"
        ])

    if "python" in role_text or "developer" in role_text:
        technical_questions.extend([
            "Explain Python decorators.",
            "What are Python virtual environments?",
            "What is object-oriented programming?"
        ])

        study_topics.extend([
            "Python OOP",
            "Flask",
            "SQLAlchemy",
            "Data Structures"
        ])

    if not technical_questions:
        technical_questions.append(
            "Review the job description and prepare role-specific technical concepts."
        )

    return behavioral_questions, technical_questions, study_topics