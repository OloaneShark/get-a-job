
import re
import threading
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from urllib.parse import (
    urljoin,
    urlparse,
)

from bs4 import BeautifulSoup

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import fetch_html
from services.job_sources.job_match_service import (
    job_matches_profile,
)


class YCombinatorJobSource(BaseJobSource):
    source_name = "Y Combinator"
    source_type = "y_combinator"
    requires_company_config = False

    listing_url = (
        "https://www.ycombinator.com/jobs/role"
    )
    base_url = "https://www.ycombinator.com/"
    cache_duration = timedelta(hours=6)
    max_workers = 8

    COUNTRY_ALIASES = {'AW': 'Aruba', 'AF': 'Afghanistan', 'AO': 'Angola', 'AI': 'Anguilla', 'AX': 'Åland Islands', 'AL': 'Albania', 'AD': 'Andorra', 'AE': 'United Arab Emirates', 'AR': 'Argentina', 'AM': 'Armenia', 'AS': 'American Samoa', 'AQ': 'Antarctica', 'TF': 'French Southern Territories', 'AG': 'Antigua and Barbuda', 'AU': 'Australia', 'AT': 'Austria', 'AZ': 'Azerbaijan', 'BI': 'Burundi', 'BE': 'Belgium', 'BJ': 'Benin', 'BQ': 'Bonaire, Sint Eustatius and Saba', 'BF': 'Burkina Faso', 'BD': 'Bangladesh', 'BG': 'Bulgaria', 'BH': 'Bahrain', 'BS': 'Bahamas', 'BA': 'Bosnia and Herzegovina', 'BL': 'Saint Barthélemy', 'BY': 'Belarus', 'BZ': 'Belize', 'BM': 'Bermuda', 'BO': 'Bolivia, Plurinational State of', 'BR': 'Brazil', 'BB': 'Barbados', 'BN': 'Brunei Darussalam', 'BT': 'Bhutan', 'BV': 'Bouvet Island', 'BW': 'Botswana', 'CF': 'Central African Republic', 'CA': 'Canada', 'CC': 'Cocos (Keeling) Islands', 'CH': 'Switzerland', 'CL': 'Chile', 'CN': 'China', 'CI': "Côte d'Ivoire", 'CM': 'Cameroon', 'CD': 'Congo, The Democratic Republic of the', 'CG': 'Congo', 'CK': 'Cook Islands', 'CO': 'Colombia', 'KM': 'Comoros', 'CV': 'Cabo Verde', 'CR': 'Costa Rica', 'CU': 'Cuba', 'CW': 'Curaçao', 'CX': 'Christmas Island', 'KY': 'Cayman Islands', 'CY': 'Cyprus', 'CZ': 'Czechia', 'DE': 'Germany', 'DJ': 'Djibouti', 'DM': 'Dominica', 'DK': 'Denmark', 'DO': 'Dominican Republic', 'DZ': 'Algeria', 'EC': 'Ecuador', 'EG': 'Egypt', 'ER': 'Eritrea', 'EH': 'Western Sahara', 'ES': 'Spain', 'EE': 'Estonia', 'ET': 'Ethiopia', 'FI': 'Finland', 'FJ': 'Fiji', 'FK': 'Falkland Islands (Malvinas)', 'FR': 'France', 'FO': 'Faroe Islands', 'FM': 'Micronesia, Federated States of', 'GA': 'Gabon', 'GB': 'United Kingdom', 'GE': 'Georgia', 'GG': 'Guernsey', 'GH': 'Ghana', 'GI': 'Gibraltar', 'GN': 'Guinea', 'GP': 'Guadeloupe', 'GM': 'Gambia', 'GW': 'Guinea-Bissau', 'GQ': 'Equatorial Guinea', 'GR': 'Greece', 'GD': 'Grenada', 'GL': 'Greenland', 'GT': 'Guatemala', 'GF': 'French Guiana', 'GU': 'Guam', 'GY': 'Guyana', 'HK': 'Hong Kong', 'HM': 'Heard Island and McDonald Islands', 'HN': 'Honduras', 'HR': 'Croatia', 'HT': 'Haiti', 'HU': 'Hungary', 'ID': 'Indonesia', 'IM': 'Isle of Man', 'IN': 'India', 'IO': 'British Indian Ocean Territory', 'IE': 'Ireland', 'IR': 'Iran, Islamic Republic of', 'IQ': 'Iraq', 'IS': 'Iceland', 'IL': 'Israel', 'IT': 'Italy', 'JM': 'Jamaica', 'JE': 'Jersey', 'JO': 'Jordan', 'JP': 'Japan', 'KZ': 'Kazakhstan', 'KE': 'Kenya', 'KG': 'Kyrgyzstan', 'KH': 'Cambodia', 'KI': 'Kiribati', 'KN': 'Saint Kitts and Nevis', 'KR': 'Korea, Republic of', 'KW': 'Kuwait', 'LA': "Lao People's Democratic Republic", 'LB': 'Lebanon', 'LR': 'Liberia', 'LY': 'Libya', 'LC': 'Saint Lucia', 'LI': 'Liechtenstein', 'LK': 'Sri Lanka', 'LS': 'Lesotho', 'LT': 'Lithuania', 'LU': 'Luxembourg', 'LV': 'Latvia', 'MO': 'Macao', 'MF': 'Saint Martin (French part)', 'MA': 'Morocco', 'MC': 'Monaco', 'MD': 'Moldova, Republic of', 'MG': 'Madagascar', 'MV': 'Maldives', 'MX': 'Mexico', 'MH': 'Marshall Islands', 'MK': 'North Macedonia', 'ML': 'Mali', 'MT': 'Malta', 'MM': 'Myanmar', 'ME': 'Montenegro', 'MN': 'Mongolia', 'MP': 'Northern Mariana Islands', 'MZ': 'Mozambique', 'MR': 'Mauritania', 'MS': 'Montserrat', 'MQ': 'Martinique', 'MU': 'Mauritius', 'MW': 'Malawi', 'MY': 'Malaysia', 'YT': 'Mayotte', 'NA': 'Namibia', 'NC': 'New Caledonia', 'NE': 'Niger', 'NF': 'Norfolk Island', 'NG': 'Nigeria', 'NI': 'Nicaragua', 'NU': 'Niue', 'NL': 'Netherlands', 'NO': 'Norway', 'NP': 'Nepal', 'NR': 'Nauru', 'NZ': 'New Zealand', 'OM': 'Oman', 'PK': 'Pakistan', 'PA': 'Panama', 'PN': 'Pitcairn', 'PE': 'Peru', 'PH': 'Philippines', 'PW': 'Palau', 'PG': 'Papua New Guinea', 'PL': 'Poland', 'PR': 'Puerto Rico', 'KP': "Korea, Democratic People's Republic of", 'PT': 'Portugal', 'PY': 'Paraguay', 'PS': 'Palestine, State of', 'PF': 'French Polynesia', 'QA': 'Qatar', 'RE': 'Réunion', 'RO': 'Romania', 'RU': 'Russian Federation', 'RW': 'Rwanda', 'SA': 'Saudi Arabia', 'SD': 'Sudan', 'SN': 'Senegal', 'SG': 'Singapore', 'GS': 'South Georgia and the South Sandwich Islands', 'SH': 'Saint Helena, Ascension and Tristan da Cunha', 'SJ': 'Svalbard and Jan Mayen', 'SB': 'Solomon Islands', 'SL': 'Sierra Leone', 'SV': 'El Salvador', 'SM': 'San Marino', 'SO': 'Somalia', 'PM': 'Saint Pierre and Miquelon', 'RS': 'Serbia', 'SS': 'South Sudan', 'ST': 'Sao Tome and Principe', 'SR': 'Suriname', 'SK': 'Slovakia', 'SI': 'Slovenia', 'SE': 'Sweden', 'SZ': 'Eswatini', 'SX': 'Sint Maarten (Dutch part)', 'SC': 'Seychelles', 'SY': 'Syrian Arab Republic', 'TC': 'Turks and Caicos Islands', 'TD': 'Chad', 'TG': 'Togo', 'TH': 'Thailand', 'TJ': 'Tajikistan', 'TK': 'Tokelau', 'TM': 'Turkmenistan', 'TL': 'Timor-Leste', 'TO': 'Tonga', 'TT': 'Trinidad and Tobago', 'TN': 'Tunisia', 'TR': 'Türkiye', 'TV': 'Tuvalu', 'TW': 'Taiwan, Province of China', 'TZ': 'Tanzania, United Republic of', 'UG': 'Uganda', 'UA': 'Ukraine', 'UM': 'United States Minor Outlying Islands', 'UY': 'Uruguay', 'US': 'United States', 'UZ': 'Uzbekistan', 'VA': 'Holy See (Vatican City State)', 'VC': 'Saint Vincent and the Grenadines', 'VE': 'Venezuela, Bolivarian Republic of', 'VG': 'Virgin Islands, British', 'VI': 'Virgin Islands, U.S.', 'VN': 'Viet Nam', 'VU': 'Vanuatu', 'WF': 'Wallis and Futuna', 'WS': 'Samoa', 'YE': 'Yemen', 'ZA': 'South Africa', 'ZM': 'Zambia', 'ZW': 'Zimbabwe'}

    _cache_lock = threading.Lock()
    _cached_jobs = None
    _cache_fetched_at = None
    _cached_stats = None

    def __init__(self):
        self._prepared_jobs = None
        self._prepared_stats = None

    @classmethod
    def cache_is_fresh(cls):
        return (
            cls._cached_jobs is not None
            and cls._cache_fetched_at is not None
            and (
                datetime.now(timezone.utc)
                - cls._cache_fetched_at
            ) < cls.cache_duration
        )

    @staticmethod
    def normalize_space(value):
        return re.sub(
            r"\s+",
            " ",
            str(value or ""),
        ).strip()

    @classmethod
    def discover_job_urls(cls):
        html = fetch_html(
            cls.listing_url,
            timeout=30,
        )
        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        urls = []
        seen = set()

        for anchor in soup.find_all(
            "a",
            href=True,
        ):
            absolute_url = urljoin(
                cls.base_url,
                anchor.get("href"),
            )
            parsed = urlparse(
                absolute_url
            )

            if parsed.netloc not in {
                "www.ycombinator.com",
                "ycombinator.com",
            }:
                continue

            if not re.fullmatch(
                r"/companies/[^/]+/jobs/[^/]+",
                parsed.path.rstrip("/"),
            ):
                continue

            canonical = (
                "https://www.ycombinator.com"
                + parsed.path.rstrip("/")
            )

            if canonical in seen:
                continue

            seen.add(canonical)
            urls.append(canonical)

        print(
            "Y COMBINATOR DISCOVERY | "
            f"Unique public engineering jobs: "
            f"{len(urls)}"
        )

        return urls

    @classmethod
    def normalized_lines(cls, root):
        return [
            cls.normalize_space(value)
            for value in root.stripped_strings
            if cls.normalize_space(value)
        ]

    @classmethod
    def extract_labeled_value(
        cls,
        lines,
        label,
    ):
        normalized_label = (
            label.casefold()
        )

        for index, value in enumerate(
            lines
        ):
            if (
                value.casefold()
                != normalized_label
            ):
                continue

            if index + 1 >= len(lines):
                return None

            return lines[
                index + 1
            ]

        return None

    @classmethod
    def parse_header_metadata(
        cls,
        lines,
        title,
    ):
        try:
            title_index = lines.index(
                title
            )
        except ValueError:
            return None, None

        job_type_index = None

        for index in range(
            title_index + 1,
            len(lines),
        ):
            if (
                lines[index].casefold()
                == "job type"
            ):
                job_type_index = index
                break

        if job_type_index is None:
            return None, None

        metadata = cls.normalize_space(
            " ".join(
                lines[
                    title_index + 1:
                    job_type_index
                ]
            )
        )

        if not metadata:
            return None, None

        parts = [
            cls.normalize_space(part)
            for part in metadata.split("•")
            if cls.normalize_space(part)
        ]

        def looks_like_salary(value):
            text = str(
                value or ""
            )

            return bool(
                re.search(
                    r"(?:[$€£₹]"
                    r"|\b(?:USD|EUR|GBP|CAD|AUD|"
                    r"INR|JPY|CHF)\b)",
                    text,
                    flags=re.IGNORECASE,
                )
                and re.search(
                    r"\d",
                    text,
                )
            )

        def looks_like_equity(value):
            text = cls.normalize_space(
                value
            )

            return bool(
                re.fullmatch(
                    r"\d+(?:\.\d+)?%\s*"
                    r"(?:-|–|—|to)\s*"
                    r"\d+(?:\.\d+)?%",
                    text,
                    flags=re.IGNORECASE,
                )
            )

        salary = None
        location_parts = []

        for part in parts:
            if (
                salary is None
                and looks_like_salary(
                    part
                )
            ):
                salary = part
                continue

            if looks_like_equity(
                part
            ):
                continue

            location_parts.append(
                part
            )

        location = cls.normalize_space(
            " ".join(
                location_parts
            )
        ) or None

        return salary, location

    @classmethod
    def extract_about_role(
        cls,
        lines,
        company,
    ):
        start = None

        for index, value in enumerate(
            lines
        ):
            if (
                value.casefold()
                == "about the role"
            ):
                start = index + 1
                break

        if start is None:
            return None

        company_heading = (
            f"about {company}"
            .casefold()
        )
        stop = len(lines)

        for index in range(
            start,
            len(lines),
        ):
            normalized = (
                lines[index]
                .casefold()
            )

            if normalized in {
                "about the interview",
                company_heading,
            }:
                stop = index
                break

        description = (
            "\n".join(
                lines[start:stop]
            )
            .strip()
        )

        return description or None

    @classmethod
    def normalize_employment_type(
        cls,
        value,
    ):
        normalized = re.sub(
            r"[\s_-]+",
            " ",
            str(value or "")
            .strip()
            .lower(),
        )

        mapping = {
            "full time": "Full-time",
            "part time": "Part-time",
            "contract": "Contract",
            "contractor": "Contract",
            "temporary": "Temporary",
            "temp": "Temporary",
            "intern": "Internship",
            "internship": "Internship",
        }

        return mapping.get(
            normalized,
            cls.normalize_space(value)
            or None,
        )

    @classmethod
    def normalize_seniority(
        cls,
        title,
    ):
        text = (
            cls.normalize_space(
                title
            )
            .casefold()
        )

        patterns = (
            (
                "manager",
                r"\b(?:manager|director|head|vp|"
                r"vice president)\b",
            ),
            (
                "principal",
                r"\bprincipal\b",
            ),
            (
                "staff",
                r"\bstaff\b",
            ),
            (
                "lead",
                r"\blead\b",
            ),
            (
                "senior",
                r"\b(?:senior|sr)\b",
            ),
            (
                "junior",
                r"\b(?:junior|jr)\b",
            ),
            (
                "entry",
                r"\b(?:entry|new grad|graduate)\b",
            ),
            (
                "intern",
                r"\b(?:intern|internship|co-op|coop)\b",
            ),
            (
                "mid",
                r"\b(?:mid|intermediate)\b",
            ),
        )

        for level, pattern in patterns:
            if re.search(
                pattern,
                text,
            ):
                return level

        return None

    @classmethod
    def normalize_remote_location(
        cls,
        value,
    ):
        normalized = (
            cls.normalize_space(
                value
            )
        )

        if not normalized:
            return None

        if re.fullmatch(
            r"[A-Za-z]{2}",
            normalized,
        ):
            code = normalized.upper()

            return (
                cls.COUNTRY_ALIASES.get(
                    code
                )
                or normalized
            )

        trailing_code = re.search(
            r",\s*([A-Za-z]{2})$",
            normalized,
        )

        if trailing_code:
            code = (
                trailing_code
                .group(1)
                .upper()
            )
            country = (
                cls.COUNTRY_ALIASES.get(
                    code
                )
            )

            if country:
                normalized = (
                    normalized[
                        :trailing_code.start()
                    ]
                    + ", "
                    + country
                )

        return normalized

    @classmethod
    def remote_scope(
        cls,
        location,
    ):
        text = cls.normalize_space(
            location
        )

        if not text:
            return None, []

        match = re.search(
            r"\bRemote\s*\(([^)]+)\)",
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            return None, []

        raw_allowed = (
            match.group(1)
        )
        pieces = [
            cls.normalize_space(piece)
            for piece in re.split(
                r";",
                raw_allowed,
            )
            if cls.normalize_space(
                piece
            )
        ]

        allowed = []

        for piece in pieces:
            normalized = (
                cls.normalize_remote_location(
                    piece
                )
            )

            if (
                normalized
                and normalized
                not in allowed
            ):
                allowed.append(
                    normalized
                )

        if not allowed:
            return None, []

        return (
            "selected_locations",
            allowed,
        )

    @classmethod
    def workplace_type(
        cls,
        title,
        location,
        description,
    ):
        location_text = (
            cls.normalize_space(
                location
            )
            .casefold()
        )

        if "remote" in location_text:
            return "Remote"

        combined = " ".join(
            [
                cls.normalize_space(
                    title
                ),
                cls.normalize_space(
                    description
                ),
            ]
        ).casefold()

        if re.search(
            r"\bhybrid\b",
            combined,
        ):
            return "Hybrid"

        return "On-site"

    @classmethod
    def find_apply_url(
        cls,
        root,
        posting_url,
    ):
        for anchor in root.find_all(
            "a",
            href=True,
        ):
            text = cls.normalize_space(
                anchor.get_text(
                    " ",
                    strip=True,
                )
            ).casefold()

            if not (
                text.startswith(
                    "apply to role"
                )
                or text.startswith(
                    "apply for role"
                )
            ):
                continue

            href = cls.normalize_space(
                anchor.get("href")
            )

            if not href:
                continue

            return urljoin(
                cls.base_url,
                href,
            )

        return posting_url

    @classmethod
    def parse_job_page(
        cls,
        posting_url,
    ):
        html = fetch_html(
            posting_url,
            timeout=30,
        )
        soup = BeautifulSoup(
            html,
            "html.parser",
        )
        root = (
            soup.find("main")
            or soup
        )

        title_element = root.find(
            "h1"
        )

        if title_element is None:
            return None

        title = cls.normalize_space(
            title_element.get_text(
                " ",
                strip=True,
            )
        )

        company_anchor = root.find(
            "a",
            href=re.compile(
                r"^/companies/[^/]+/?$"
            ),
        )

        if company_anchor is None:
            return None

        company = cls.normalize_space(
            company_anchor.get_text(
                " ",
                strip=True,
            )
        )

        if not company or not title:
            return None

        lines = cls.normalized_lines(
            root
        )

        role = cls.extract_labeled_value(
            lines,
            "Role",
        )

        if (
            not role
            or "engineering"
            not in role.casefold()
        ):
            return None

        employment_type = (
            cls.normalize_employment_type(
                cls.extract_labeled_value(
                    lines,
                    "Job type",
                )
            )
        )
        experience = (
            cls.extract_labeled_value(
                lines,
                "Experience",
            )
        )
        visa = (
            cls.extract_labeled_value(
                lines,
                "Visa",
            )
        )
        skills = (
            cls.extract_labeled_value(
                lines,
                "Skills",
            )
        )

        salary, location = (
            cls.parse_header_metadata(
                lines,
                title,
            )
        )

        description = (
            cls.extract_about_role(
                lines,
                company,
            )
        )

        metadata_lines = []

        if experience:
            metadata_lines.append(
                f"YC Experience: "
                f"{experience}"
            )

        if visa:
            metadata_lines.append(
                f"YC Visa: {visa}"
            )

        if skills:
            metadata_lines.append(
                f"YC Skills: {skills}"
            )

        if role:
            metadata_lines.append(
                f"YC Role: {role}"
            )

        description_parts = []

        if description:
            description_parts.append(
                description
            )

        if metadata_lines:
            description_parts.append(
                "\n".join(
                    metadata_lines
                )
            )

        job_description = (
            "\n\n".join(
                description_parts
            )
            or None
        )

        departments = [
            cls.normalize_space(value)
            for value in role.split(",")
            if cls.normalize_space(
                value
            )
        ]

        if skills:
            for skill in skills.split(","):
                normalized_skill = (
                    cls.normalize_space(
                        skill
                    )
                )

                if (
                    normalized_skill
                    and normalized_skill
                    not in departments
                ):
                    departments.append(
                        normalized_skill
                    )

        workplace = (
            cls.workplace_type(
                title,
                location,
                description,
            )
        )

        remote_candidate_scope = None
        remote_allowed_locations = []

        if workplace == "Remote":
            (
                remote_candidate_scope,
                remote_allowed_locations,
            ) = cls.remote_scope(
                location
            )

        if (
            workplace == "Remote"
            and cls.normalize_space(
                location
            ).casefold()
            in {
                "remote",
                "fully remote",
            }
        ):
            location_source = (
                "yc_public_job_page_unspecified"
            )
            location_confidence = 0.0
        else:
            location_source = (
                "yc_public_job_page"
            )
            location_confidence = 1.0

        parsed_path = urlparse(
            posting_url
        ).path.rstrip("/")
        external_id = (
            parsed_path.rsplit(
                "/",
                1,
            )[-1]
        )

        seniority = (
            cls.normalize_seniority(
                title
            )
        )

        return {
            "source": cls.source_name,
            "external_id": external_id,
            "company_name": company,
            "position_title": title,
            "location": location,
            "location_source": (
                location_source
            ),
            "location_confidence": (
                location_confidence
            ),
            "employment_type": (
                employment_type
            ),
            "salary": salary,
            "visa_sponsorship": (
                "Yes"
                if (
                    cls.normalize_space(
                        visa
                    ).casefold()
                    == "will sponsor"
                )
                else "Unknown"
            ),
            "overseas_applicant_status": (
                "Unknown"
            ),
            "posting_url": posting_url,
            "apply_url": (
                cls.find_apply_url(
                    root,
                    posting_url,
                )
            ),
            "job_description": (
                job_description
            ),
            "departments": departments,
            "offices": (
                [location]
                if location
                else []
            ),
            "is_remote": (
                workplace == "Remote"
            ),
            "workplace_type": workplace,
            "remote_candidate_scope": (
                remote_candidate_scope
            ),
            "remote_allowed_locations": (
                remote_allowed_locations
            ),
            "published_at": None,
            "experience_level": seniority,
            "seniority_level": seniority,
            "source_experience": experience,
            "source_visa": visa,
            "source_skills": skills,
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @classmethod
    def fetch_jobs(cls):
        posting_urls = (
            cls.discover_job_urls()
        )

        if not posting_urls:
            raise RuntimeError(
                "Y Combinator returned no "
                "discoverable public "
                "engineering job URLs."
            )

        jobs = []
        failed = 0

        with ThreadPoolExecutor(
            max_workers=cls.max_workers
        ) as executor:
            futures = {
                executor.submit(
                    cls.parse_job_page,
                    posting_url,
                ): posting_url
                for posting_url
                in posting_urls
            }

            for future in as_completed(
                futures
            ):
                posting_url = futures[
                    future
                ]

                try:
                    job = future.result()
                except Exception as error:
                    failed += 1
                    print(
                        "Y COMBINATOR DETAIL FAILED | "
                        f"URL: {posting_url} | "
                        f"Error: {error}"
                    )
                    continue

                if job is None:
                    failed += 1
                    print(
                        "Y COMBINATOR PARSE SKIP | "
                        f"URL: {posting_url}"
                    )
                    continue

                jobs.append(job)

        deduplicated = {}

        for job in jobs:
            key = str(
                job.get("external_id")
                or job.get(
                    "posting_url"
                )
                or ""
            ).strip()

            if not key:
                continue

            deduplicated[key] = job

        unique_jobs = list(
            deduplicated.values()
        )

        stats = {
            "discovered": len(
                posting_urls
            ),
            "parsed": len(jobs),
            "failed": failed,
            "unique": len(
                unique_jobs
            ),
        }

        print(
            "Y COMBINATOR FEED | "
            f"Discovered: "
            f"{stats['discovered']} | "
            f"Parsed: {stats['parsed']} | "
            f"Failed: {stats['failed']} | "
            f"Unique: {stats['unique']}"
        )

        return (
            unique_jobs,
            stats,
        )

    def prepare(
        self,
        profiles,
    ):
        source_class = type(self)

        with source_class._cache_lock:
            if source_class.cache_is_fresh():
                self._prepared_jobs = list(
                    source_class._cached_jobs
                )
                self._prepared_stats = dict(
                    source_class._cached_stats
                    or {}
                )

                print(
                    "Y COMBINATOR CACHE | "
                    f"Using "
                    f"{len(self._prepared_jobs)} "
                    "normalized jobs."
                )

                return list(
                    self._prepared_jobs
                )

        jobs, stats = (
            source_class.fetch_jobs()
        )

        with source_class._cache_lock:
            source_class._cached_jobs = list(
                jobs
            )
            source_class._cache_fetched_at = (
                datetime.now(
                    timezone.utc
                )
            )
            source_class._cached_stats = dict(
                stats
            )

        self._prepared_jobs = list(
            jobs
        )
        self._prepared_stats = dict(
            stats
        )

        return list(
            self._prepared_jobs
        )

    def search(
        self,
        profile,
        source_config=None,
    ):
        if self._prepared_jobs is None:
            self.prepare(
                [profile]
            )

        matching_jobs = [
            job
            for job in self._prepared_jobs
            if job_matches_profile(
                job,
                profile,
            )
        ]

        print(
            "Y COMBINATOR SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Matched: {len(matching_jobs)}"
        )

        return matching_jobs
