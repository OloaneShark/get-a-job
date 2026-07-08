
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

    return {
        "page_title": page_title,
        "company_name": "",
        "position_title": page_title,
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
