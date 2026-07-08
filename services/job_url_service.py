
import re
import requests
from bs4 import BeautifulSoup


STOP_WORDS = [
    "newsletter",
    "sign up",
    "login",
    "logout",
    "dashboard",
    "search jobs",
    "company list",
    "privacy policy",
    "terms of service",
    "similar jobs",
    "share this job",
]


START_MARKERS = [
    "overview",
    "about the role",
    "job description",
    "responsibilities",
    "what you'll do",
    "requirements",
    "required skills",
]


def extract_job_from_url(url):
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    page_title = get_page_title(soup)

    remove_noise(soup)

    main = find_main_content(soup)
    raw_text = extract_clean_lines(main)
    job_text = trim_to_likely_job_content(raw_text)
    structured = extract_structured_job_fields(page_title, job_text)
    
    return {
        "page_title": page_title,
        "company_name": structured["company_name"],
        "position_title": structured["position_title"],
        "location": structured["location"],
        "salary": structured["salary"],
        "visa_sponsorship": structured["visa_sponsorship"],
        "job_description": job_text[:12000],
    }


def fetch_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Get-A-JobBot/1.0)"
    }

    response = requests.get(url, headers=headers, timeout=12)
    response.raise_for_status()
    return response.text


def get_page_title(soup):
    title = soup.find("title")
    return title.get_text(" ", strip=True) if title else ""


def remove_noise(soup):
    for tag in soup([
        "script",
        "style",
        "noscript",
        "nav",
        "footer",
        "header",
        "aside",
        "svg",
        "button",
        "form",
    ]):
        tag.decompose()


def find_main_content(soup):
    candidates = [
        soup.find("main"),
        soup.find("article"),
        soup.find(attrs={"role": "main"}),
    ]

    for candidate in candidates:
        if candidate:
            return candidate

    return soup.body or soup


def extract_clean_lines(element):
    text = element.get_text("\n", strip=True)
    lines = []

    for line in text.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()

        if len(cleaned) < 2:
            continue

        if is_noise_line(cleaned):
            continue

        lines.append(cleaned)

    return "\n".join(lines)


def is_noise_line(line):
    lowered = line.lower()

    if lowered in STOP_WORDS:
        return True

    if len(line) <= 20 and any(word in lowered for word in STOP_WORDS):
        return True

    return False


def trim_to_likely_job_content(text):
    lowered = text.lower()
    start_index = None

    for marker in START_MARKERS:
        index = lowered.find(marker)
        if index != -1:
            if start_index is None or index < start_index:
                start_index = index

    if start_index is not None:
        text = text[start_index:]

    return text.strip()


def extract_structured_job_fields(page_title, job_text):
    return {
        "company_name": guess_company(page_title, job_text),
        "position_title": guess_position(page_title, job_text),
        "location": guess_location(job_text),
        "salary": guess_salary(job_text),
        "visa_sponsorship": guess_visa(job_text),
    }


def guess_position(page_title, job_text):
    if page_title:
        title = page_title.replace("|", "-").split("-")[0].strip()
        return title[:150]

    first_line = job_text.splitlines()[0] if job_text else ""
    return first_line[:150]


def guess_company(page_title, job_text):
    lowered = page_title.lower()

    if " at " in lowered:
        parts = page_title.split(" at ", 1)
        company_part = parts[1]
        company_part = company_part.split("|")[0].split("-")[0].strip()
        return company_part[:150]

    return ""


def guess_location(job_text):
    common_locations = [
        "Tokyo",
        "Japan",
        "Remote",
        "Hybrid",
        "Osaka",
        "Atlanta",
        "United States",
    ]

    for location in common_locations:
        if location.lower() in job_text.lower():
            return location

    return ""


def guess_salary(job_text):
    import re

    patterns = [
        r"\$[0-9,]+(?:\s*-\s*\$[0-9,]+)?",
        r"¥[0-9,]+(?:\s*-\s*¥[0-9,]+)?",
        r"[0-9]+(?:\.[0-9]+)?M\s*JPY",
    ]

    for pattern in patterns:
        match = re.search(pattern, job_text, re.IGNORECASE)
        if match:
            return match.group(0)

    return ""


def guess_visa(job_text):
    lowered = job_text.lower()

    positive = [
        "visa sponsorship",
        "sponsor visa",
        "work visa support",
        "relocation support",
    ]

    negative = [
        "no visa sponsorship",
        "unable to sponsor",
        "does not sponsor",
    ]

    for phrase in negative:
        if phrase in lowered:
            return False

    for phrase in positive:
        if phrase in lowered:
            return True

    return False

