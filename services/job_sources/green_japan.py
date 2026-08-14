
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_response
from services.job_sources.job_match_service import (
    collect_match_diagnostics,
    format_match_diagnostics,
    job_matches_profile,
)


class GreenJapanJobSource(BaseJobSource):
    source_name = "Green Japan"
    source_type = "green_japan"
    requires_company_config = False

    base_url = "https://www.green-japan.com"
    listing_url_template = (
        "https://www.green-japan.com/"
        "jobtype-h/190/01?page={page}"
    )
    cache_duration = timedelta(hours=6)
    max_workers = 4
    max_job_urls = 110
    max_listing_pages = 5
    request_headers = {"Accept-Language": "ja,en-US;q=0.8,en;q=0.7"}

    _cache_lock = threading.Lock()
    _cached_jobs = None
    _cache_fetched_at = None
    _cached_stats = None

    PREFECTURES = {
        "北海道": "Hokkaido", "青森県": "Aomori", "岩手県": "Iwate",
        "宮城県": "Miyagi", "秋田県": "Akita", "山形県": "Yamagata",
        "福島県": "Fukushima", "茨城県": "Ibaraki", "栃木県": "Tochigi",
        "群馬県": "Gunma", "埼玉県": "Saitama", "千葉県": "Chiba",
        "東京都": "Tokyo", "神奈川県": "Kanagawa", "新潟県": "Niigata",
        "富山県": "Toyama", "石川県": "Ishikawa", "福井県": "Fukui",
        "山梨県": "Yamanashi", "長野県": "Nagano", "岐阜県": "Gifu",
        "静岡県": "Shizuoka", "愛知県": "Aichi", "三重県": "Mie",
        "滋賀県": "Shiga", "京都府": "Kyoto", "大阪府": "Osaka",
        "兵庫県": "Hyogo", "奈良県": "Nara", "和歌山県": "Wakayama",
        "鳥取県": "Tottori", "島根県": "Shimane", "岡山県": "Okayama",
        "広島県": "Hiroshima", "山口県": "Yamaguchi", "徳島県": "Tokushima",
        "香川県": "Kagawa", "愛媛県": "Ehime", "高知県": "Kochi",
        "福岡県": "Fukuoka", "佐賀県": "Saga", "長崎県": "Nagasaki",
        "熊本県": "Kumamoto", "大分県": "Oita", "宮崎県": "Miyazaki",
        "鹿児島県": "Kagoshima", "沖縄県": "Okinawa",
    }

    ROLE_PATTERNS = (
        (r"DevSecOps", "DevSecOps"),
        (r"\bSRE\b|Site Reliability", "SRE"),
        (r"フルスタック|\bfull[- ]?stack\b", "Full Stack Developer"),
        (r"バックエンド|サーバーサイド|\bback[- ]?end\b", "Backend Developer"),
        (r"フロントエンド|\bfront[- ]?end\b", "Frontend Developer"),
        (r"セキュリティエンジニア|サイバーセキュリティ|Security Engineer", "Security Engineer"),
        (r"クラウドエンジニア|Cloud Engineer", "Cloud Engineer"),
        (r"\bDevOps\b", "DevOps"),
        (r"インフラエンジニア|Infrastructure Engineer", "Infrastructure Engineer"),
        (r"ネットワークエンジニア|Network Engineer", "Network Engineer"),
        (r"社内SE|情報システム|情シス", "Systems Administrator"),
        (r"サーバーエンジニア|システムエンジニア|\bSE\b", "Systems Engineer"),
        (r"データエンジニア|Data Engineer", "Data Engineer"),
        (r"データサイエンティスト|Data Scientist", "Data Scientist"),
        (r"機械学習エンジニア|Machine Learning Engineer|\bML Engineer\b", "Machine Learning Engineer"),
        (r"AIエンジニア|AI Engineer", "AI Engineer"),
        (r"QAエンジニア|品質保証|Quality Assurance", "QA Engineer"),
        (r"iOSエンジニア|Androidエンジニア|モバイルエンジニア|アプリエンジニア|Mobile Developer", "Mobile Developer"),
        (r"ソフトウェアエンジニア|Software Engineer", "Software Engineer"),
        (r"Webエンジニア|ウェブエンジニア|Web Developer", "Web Developer"),
        (r"開発エンジニア", "Software Engineer"),
    )

    def __init__(self):
        self._prepared_jobs = None
        self._prepared_stats = None

    @classmethod
    def cache_is_fresh(cls):
        return (
            cls._cached_jobs is not None
            and cls._cache_fetched_at is not None
            and datetime.now(timezone.utc) - cls._cache_fetched_at
            < cls.cache_duration
        )

    @staticmethod
    def normalize_space(value):
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @classmethod
    def fetch_html(cls, url):
        return fetch_response(
            url,
            headers=cls.request_headers,
            timeout=30,
        ).text

    @classmethod
    def normalize_job_url(cls, raw_url):
        absolute = urljoin(cls.base_url, cls.normalize_space(raw_url))
        parsed = urlparse(absolute)
        if parsed.netloc.lower() not in {"green-japan.com", "www.green-japan.com"}:
            return None
        match = re.fullmatch(r"/company/(\d+)/job/(\d+)/?", parsed.path)
        if not match:
            return None
        return (
            f"https://www.green-japan.com/company/{match.group(1)}"
            f"/job/{match.group(2)}"
        )

    @classmethod
    def discover_job_urls(cls):
        urls = []
        seen = set()

        for page in range(1, cls.max_listing_pages + 1):
            listing_url = cls.listing_url_template.format(page=page)
            soup = BeautifulSoup(
                cls.fetch_html(listing_url),
                "html.parser",
            )

            page_urls = []
            page_seen = set()

            for anchor in soup.find_all("a", href=True):
                url = cls.normalize_job_url(anchor.get("href"))

                if not url or url in page_seen:
                    continue

                page_seen.add(url)
                page_urls.append(url)

            new_count = 0

            for url in page_urls:
                if url in seen:
                    continue

                seen.add(url)
                urls.append(url)
                new_count += 1

                if len(urls) >= cls.max_job_urls:
                    break

            print(
                "GREEN JAPAN LISTING PAGE | "
                f"Page: {page} | "
                f"Page URLs: {len(page_urls)} | "
                f"New URLs: {new_count} | "
                f"Total unique: {len(urls)}"
            )

            if len(urls) >= cls.max_job_urls:
                break

            if page > 1 and new_count == 0:
                break

        print(
            "GREEN JAPAN DISCOVERY | "
            f"Unique public job URLs: {len(urls)}"
        )

        return urls

    @staticmethod
    def is_job_posting(value):
        if not isinstance(value, dict):
            return False
        value_type = value.get("@type")
        if isinstance(value_type, list):
            return "JobPosting" in value_type
        return value_type == "JobPosting"

    @classmethod
    def find_job_posting_json(cls, soup):
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = script.string or script.get_text()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue

            candidates = payload if isinstance(payload, list) else [payload]
            for candidate in candidates:
                if cls.is_job_posting(candidate):
                    return candidate
                if not isinstance(candidate, dict):
                    continue
                graph = candidate.get("@graph")
                if isinstance(graph, list):
                    for item in graph:
                        if cls.is_job_posting(item):
                            return item
        return None

    @classmethod
    def page_lines(cls, soup):
        root = soup.body or soup.find("main") or soup
        return [
            cls.normalize_space(value)
            for value in root.stripped_strings
            if cls.normalize_space(value)
        ]

    @classmethod
    def labeled_value(cls, lines, label):
        for index, value in enumerate(lines):
            if cls.normalize_space(value) == label and index + 1 < len(lines):
                return cls.normalize_space(lines[index + 1])
        return None

    @classmethod
    def normalize_prefecture(cls, value):
        text = cls.normalize_space(value)
        if not text:
            return None
        for japanese, english in cls.PREFECTURES.items():
            if japanese in text:
                return f"{english}, Japan"
        if text in {"日本", "全国", "国内"}:
            return "Japan"
        return text

    @classmethod
    def extract_locations(cls, posting, lines):
        raw_locations = posting.get("jobLocation")
        if isinstance(raw_locations, dict):
            raw_locations = [raw_locations]

        locations = []
        if isinstance(raw_locations, list):
            for item in raw_locations:
                if not isinstance(item, dict):
                    continue
                address = item.get("address")
                if isinstance(address, dict):
                    item = address
                raw = (
                    item.get("addressRegion")
                    or item.get("addressLocality")
                    or item.get("name")
                )
                location = cls.normalize_prefecture(raw)
                if location and location not in locations:
                    locations.append(location)

        if not locations:
            visible = cls.labeled_value(lines, "勤務地")
            if visible:
                for piece in re.split(r"[,、，]", visible):
                    location = cls.normalize_prefecture(piece)
                    if location and location not in locations:
                        locations.append(location)

        return locations

    @classmethod
    def detect_workplace(cls, posting, page_text):
        location_type = cls.normalize_space(
            posting.get("jobLocationType")
        ).upper()
        text = page_text.casefold()

        worldwide = (
            "worldwide", "世界中", "海外から勤務", "海外からフルリモート"
        )
        full_remote = (
            "フルリモート", "完全在宅", "完全リモート",
            "全国リモート", "国内フルリモート",
        )
        hybrid = (
            "ハイブリッド", "一部リモート", "リモートワーク可",
            "リモート可", "在宅勤務可",
        )

        if location_type == "TELECOMMUTE" or any(
            term.casefold() in text for term in full_remote
        ):
            if any(term.casefold() in text for term in worldwide):
                return "Remote", True, "worldwide", []
            return "Remote", True, "selected_locations", ["Japan"]

        if any(term.casefold() in text for term in hybrid):
            return "Hybrid", True, None, []

        return "On-site", False, None, []

    @classmethod
    def format_location(cls, locations, workplace_type, remote_scope):
        if workplace_type == "Remote" and remote_scope == "worldwide":
            return "Remote Worldwide"
        if workplace_type == "Remote":
            return "Remote | Japan"
        if not locations or len(locations) >= 8:
            return "Japan"
        return " | ".join(locations[:7])

    @classmethod
    def normalize_employment_type(cls, value):
        normalized = cls.normalize_space(value).casefold()
        mapping = {
            "full_time": "Full-time", "full-time": "Full-time",
            "full time": "Full-time", "正社員": "Full-time",
            "part_time": "Part-time", "part-time": "Part-time",
            "part time": "Part-time", "アルバイト": "Part-time",
            "パート": "Part-time", "contract": "Contract",
            "contractor": "Contract", "契約社員": "Contract",
            "業務委託": "Contract", "temporary": "Temporary",
            "派遣社員": "Temporary", "intern": "Internship",
            "internship": "Internship", "インターン": "Internship",
        }
        return mapping.get(normalized)

    @classmethod
    def employment_type(cls, posting, lines):
        raw = posting.get("employmentType")
        if isinstance(raw, list):
            for item in raw:
                value = cls.normalize_employment_type(item)
                if value:
                    return value
        else:
            value = cls.normalize_employment_type(raw)
            if value:
                return value
        return cls.normalize_employment_type(
            cls.labeled_value(lines, "雇用区分")
        )

    @classmethod
    def salary(cls, posting, page_text):
        base = posting.get("baseSalary")
        if isinstance(base, list):
            base = next((x for x in base if isinstance(x, dict)), None)

        if isinstance(base, dict):
            currency = cls.normalize_space(base.get("currency")) or "JPY"
            value = base.get("value")
            if isinstance(value, dict):
                minimum = value.get("minValue") or value.get("value")
                maximum = value.get("maxValue")
                try:
                    minimum = float(minimum) if minimum is not None else None
                    maximum = float(maximum) if maximum is not None else None
                except (TypeError, ValueError):
                    minimum = maximum = None
                if minimum is not None or maximum is not None:
                    if minimum is not None and maximum is not None:
                        return f"{currency} {minimum:,.0f} - {maximum:,.0f} / year"
                    if minimum is not None:
                        return f"From {currency} {minimum:,.0f} / year"
                    return f"Up to {currency} {maximum:,.0f} / year"

        match = re.search(
            r"(\d{3,4})\s*万円\s*[〜～\-]\s*(\d{3,4})\s*万円",
            page_text,
        )
        if match:
            minimum = int(match.group(1)) * 10_000
            maximum = int(match.group(2)) * 10_000
            return f"JPY {minimum:,} - {maximum:,} / year"

        return None

    @classmethod
    def parse_datetime(cls, value):
        if not value:
            return None
        text = cls.normalize_space(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        parsed = None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue

        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def published_at(cls, posting, page_text):
        for key in ("datePosted", "datePublished", "dateModified"):
            parsed = cls.parse_datetime(posting.get(key))
            if parsed:
                return parsed

        match = re.search(r"(\d{4}/\d{1,2}/\d{1,2})\s*更新", page_text)
        return cls.parse_datetime(match.group(1)) if match else None

    @classmethod
    def augment_title(cls, title):
        for pattern, alias in cls.ROLE_PATTERNS:
            if re.search(pattern, title or "", flags=re.IGNORECASE):
                if alias.casefold() in title.casefold():
                    return title
                return f"{title} [{alias}]"
        return title

    @classmethod
    def experience_level(cls, title, description):
        title_patterns = (
            (r"インターン|intern", "intern"),
            (r"未経験|新卒|entry", "entry"),
            (r"ジュニア|junior", "junior"),
            (r"ミドル|mid[- ]?level", "mid"),
            (r"シニア|senior", "senior"),
            (r"プリンシパル|principal", "principal"),
            (r"テックリード|リードエンジニア|technical lead|tech lead", "lead"),
            (r"エンジニアリングマネージャ|Engineering Manager", "manager"),
        )
        for pattern, level in title_patterns:
            if re.search(pattern, title or "", flags=re.IGNORECASE):
                return level

        if re.search(r"未経験歓迎|実務未経験", description or "", flags=re.IGNORECASE):
            return "entry"
        return None

    @classmethod
    def visa_status(cls, page_text):
        text = page_text.casefold()
        if any(term.casefold() in text for term in (
            "ビザサポートなし", "ビザサポート対象外",
            "visa sponsorship not available", "no visa sponsorship",
        )):
            return "No"
        if any(term.casefold() in text for term in (
            "就労ビザサポート", "ビザサポートあり",
            "ビザ支援", "visa sponsorship available",
            "visa support available",
        )):
            return "Yes"
        return "Unknown"

    @classmethod
    def overseas_status(cls, page_text):
        text = page_text.casefold()
        if any(term.casefold() in text for term in (
            "海外応募不可", "日本国内在住者のみ", "国内在住者のみ",
        )):
            return "No"
        if any(term.casefold() in text for term in (
            "海外応募可", "海外から応募可", "海外在住者応募可", "国外から応募可",
        )):
            return "Yes"
        return "Unknown"

    @classmethod
    def company_name(cls, posting, soup):
        organization = posting.get("hiringOrganization")
        if isinstance(organization, dict):
            value = cls.normalize_space(organization.get("name"))
            if value:
                return value

        if soup.title:
            value = cls.normalize_space(soup.title.get_text())
            if "|" in value:
                return value.split("|", 1)[0].strip()
        return None

    @classmethod
    def normalize_job_page(cls, url, html):
        soup = BeautifulSoup(html, "html.parser")
        posting = cls.find_job_posting_json(soup)
        if not isinstance(posting, dict):
            return None

        id_match = re.search(r"/company/(\d+)/job/(\d+)", url)
        if not id_match:
            return None

        title = cls.normalize_space(posting.get("title"))
        if not title:
            h1 = soup.find("h1")
            title = cls.normalize_space(
                h1.get_text(" ", strip=True)
            ) if h1 else ""

        company = cls.company_name(posting, soup)
        if not title or not company:
            return None

        lines = cls.page_lines(soup)
        page_text = cls.normalize_space(" ".join(lines))
        description = clean_html_text(posting.get("description")) or page_text

        locations = cls.extract_locations(posting, lines)
        workplace, is_remote, remote_scope, allowed = cls.detect_workplace(
            posting,
            page_text,
        )

        return {
            "source": cls.source_name,
            "external_id": id_match.group(2),
            "company_name": company,
            "position_title": cls.augment_title(title),
            "location": cls.format_location(locations, workplace, remote_scope),
            "location_source": "green_japan_json_ld",
            "location_confidence": 1.0,
            "employment_type": cls.employment_type(posting, lines),
            "salary": cls.salary(posting, page_text),
            "visa_sponsorship": cls.visa_status(page_text),
            "overseas_applicant_status": cls.overseas_status(page_text),
            "posting_url": url,
            "apply_url": url,
            "job_description": description,
            "departments": [],
            "offices": locations,
            "is_remote": is_remote,
            "workplace_type": workplace,
            "remote_candidate_scope": remote_scope,
            "remote_allowed_locations": allowed,
            "published_at": cls.published_at(posting, page_text),
            "experience_level": cls.experience_level(title, description),
            "seniority_level": cls.experience_level(title, description),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @classmethod
    def fetch_job(cls, url):
        return cls.normalize_job_page(url, cls.fetch_html(url))

    @classmethod
    def prepare_jobs(cls):
        urls = cls.discover_job_urls()
        jobs = []
        errors = 0
        invalid = 0

        with ThreadPoolExecutor(max_workers=cls.max_workers) as executor:
            future_map = {
                executor.submit(cls.fetch_job, url): url
                for url in urls
            }

            completed = 0
            for future in as_completed(future_map):
                completed += 1
                url = future_map[future]
                try:
                    job = future.result()
                except Exception as error:
                    errors += 1
                    print(
                        "GREEN JAPAN JOB FAILED | "
                        f"URL: {url} | Error: {error}"
                    )
                    continue

                if job is None:
                    invalid += 1
                    continue

                jobs.append(job)

                if completed % 20 == 0 or completed == len(urls):
                    print(
                        "GREEN JAPAN FETCH | "
                        f"Completed: {completed}/{len(urls)} | "
                        f"Normalized: {len(jobs)} | "
                        f"Errors: {errors} | Invalid: {invalid}"
                    )

        unique = {
            str(job.get("external_id") or job.get("posting_url")): job
            for job in jobs
            if job.get("external_id") or job.get("posting_url")
        }

        prepared = list(unique.values())
        stats = {
            "discovered_urls": len(urls),
            "normalized": len(jobs),
            "invalid": invalid,
            "errors": errors,
            "unique": len(prepared),
        }

        print(
            "GREEN JAPAN FEED | "
            f"URLs: {stats['discovered_urls']} | "
            f"Normalized: {stats['normalized']} | "
            f"Invalid: {stats['invalid']} | "
            f"Errors: {stats['errors']} | "
            f"Unique: {stats['unique']}"
        )

        return prepared, stats

    def prepare(self, profiles):
        source_class = type(self)

        with source_class._cache_lock:
            if source_class.cache_is_fresh():
                self._prepared_jobs = list(source_class._cached_jobs)
                self._prepared_stats = dict(
                    source_class._cached_stats or {}
                )
                print(
                    "GREEN JAPAN CACHE | "
                    f"Using {len(self._prepared_jobs)} normalized jobs."
                )
                return list(self._prepared_jobs)

        jobs, stats = source_class.prepare_jobs()

        with source_class._cache_lock:
            source_class._cached_jobs = list(jobs)
            source_class._cache_fetched_at = datetime.now(timezone.utc)
            source_class._cached_stats = dict(stats)

        self._prepared_jobs = list(jobs)
        self._prepared_stats = dict(stats)
        return list(self._prepared_jobs)

    def search(self, profile, source_config=None):
        if self._prepared_jobs is None:
            self.prepare([profile])

        with collect_match_diagnostics() as diagnostics:
            matching_jobs = [
                job
                for job in self._prepared_jobs
                if job_matches_profile(job, profile)
            ]

        print(
            "GREEN JAPAN SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Matched: {len(matching_jobs)}"
        )

        if diagnostics["evaluated"] > 0:
            print(
                format_match_diagnostics(
                    profile.name,
                    self.source_name,
                    diagnostics,
                )
            )

        return matching_jobs
