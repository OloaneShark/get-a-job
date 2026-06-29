
def generate_interview_prep(company, role):
    behavioral_questions = [
        "Tell me about yourself.",
        "Describe a time you faced a difficult challenge.",
        "Tell me about a conflict you had with a teammate.",
        "Describe a time you failed and what you learned.",
        "Tell me about a project you are most proud of.",
        f"Why do you want to work at {company}?",
        "Tell me about a time you had to learn something quickly."
    ]

    technical_questions = []
    study_topics = []

    role_text = role.lower()

    if "security" in role_text or "cyber" in role_text:
        technical_questions.extend([
            "What is the difference between authentication and authorization?",
            "Explain the CIA Triad.",
            "What is least privilege?",
            "What is the OWASP Top 10?",
            "How would you investigate a suspicious login?"
        ])

        study_topics.extend([
            "CIA Triad",
            "Authentication and Authorization",
            "OWASP Top 10",
            "IAM",
            "Logging and Monitoring",
            "Incident Response"
        ])

    if "cloud" in role_text or "aws" in role_text:
        technical_questions.extend([
            "What is AWS IAM?",
            "How do security groups differ from NACLs?",
            "Explain AWS shared responsibility.",
            "How would you secure an S3 bucket?",
            "What is the difference between public and private subnets?"
        ])

        study_topics.extend([
            "AWS IAM",
            "S3 Security",
            "Security Groups vs NACLs",
            "VPC Basics",
            "Cloud Security Best Practices"
        ])

    if "devops" in role_text or "devsecops" in role_text:
        technical_questions.extend([
            "Explain a CI/CD pipeline.",
            "How would you secure a CI/CD pipeline?",
            "What is Docker used for?",
            "What is the purpose of environment variables?",
            "How would you prevent secrets from being committed to GitHub?"
        ])

        study_topics.extend([
            "Docker",
            "GitHub Actions",
            "CI/CD Security",
            "Secret Management",
            "Dependency Scanning",
            "Container Security"
        ])

    if "python" in role_text or "developer" in role_text or "software" in role_text:
        technical_questions.extend([
            "Explain object-oriented programming.",
            "What are Python virtual environments?",
            "What is the difference between a list, tuple, and dictionary?",
            "How does Flask handle routing?",
            "What is an ORM?"
        ])

        study_topics.extend([
            "Python OOP",
            "Flask",
            "SQLAlchemy",
            "REST APIs",
            "Databases",
            "Git"
        ])

    if "help desk" in role_text or "support" in role_text or "it technician" in role_text:
        technical_questions.extend([
            "How would you troubleshoot a computer that cannot connect to the internet?",
            "What is DNS?",
            "What is DHCP?",
            "How would you handle an upset user?",
            "What steps would you take if a user forgot their password?"
        ])

        study_topics.extend([
            "DNS",
            "DHCP",
            "Windows Troubleshooting",
            "Active Directory Basics",
            "Customer Support",
            "Ticketing Systems"
        ])

    if "data analyst" in role_text or "analyst" in role_text:
        technical_questions.extend([
            "What is the difference between SQL WHERE and HAVING?",
            "How would you clean messy data?",
            "What is a JOIN in SQL?",
            "How would you explain a technical finding to a non-technical audience?"
        ])

        study_topics.extend([
            "SQL",
            "Excel",
            "Data Cleaning",
            "Dashboards",
            "Basic Statistics",
            "Data Visualization"
        ])

    if not technical_questions:
        technical_questions.append(
            "Review the job description and prepare role-specific technical concepts."
        )

    if not study_topics:
        study_topics.append(
            "Review the job description, company mission, required tools, and your related projects."
        )

    technical_questions = list(dict.fromkeys(technical_questions))
    study_topics = list(dict.fromkeys(study_topics))

    return behavioral_questions, technical_questions, study_topics