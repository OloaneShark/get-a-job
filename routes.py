"""Live route inventory utilities for Jobfinitum.

Flask handlers currently live in app.py. This module gives developers one
canonical way to inspect that route map and detect overlapping registrations
without duplicating the handlers themselves.
"""

import os
from collections import defaultdict
from dataclasses import dataclass


IGNORED_METHODS = frozenset({"HEAD", "OPTIONS"})

SECTION_PREFIXES = (
    ("Administration", ("/admin",)),
    ("Auto Apply", ("/auto-apply", "/browser-agent")),
    ("APIs", ("/api",)),
    ("Applications", ("/applications",)),
    (
        "Authentication",
        (
            "/login",
            "/logout",
            "/register",
            "/auth",
            "/verify-email",
        ),
    ),
    ("Resumes", ("/resumes",)),
    (
        "Job Discovery",
        (
            "/jobs",
            "/discovered-jobs",
            "/saved-jobs",
            "/search-profiles",
        ),
    ),
    (
        "AI and Research",
        (
            "/ai",
            "/company-lookup",
            "/interview-prep",
            "/job-match",
        ),
    ),
    ("Account Settings", ("/settings",)),
    ("Job Descriptions", ("/job-descriptions",)),
    ("Workspace", ("/dashboard",)),
)


@dataclass(frozen=True, order=True)
class RouteRecord:
    section: str
    rule: str
    methods: tuple[str, ...]
    endpoint: str


def route_section(rule):
    normalized = str(rule or "")

    if normalized == "/":
        return "Public"

    for section, prefixes in SECTION_PREFIXES:
        if any(
            normalized == prefix
            or normalized.startswith(f"{prefix}/")
            for prefix in prefixes
        ):
            return section

    return "Other"


def registered_routes(flask_app, *, include_static=False):
    records = []

    for rule in flask_app.url_map.iter_rules():
        if not include_static and rule.endpoint == "static":
            continue

        methods = tuple(
            sorted(set(rule.methods) - IGNORED_METHODS)
        )
        records.append(
            RouteRecord(
                section=route_section(rule.rule),
                rule=rule.rule,
                methods=methods,
                endpoint=rule.endpoint,
            )
        )

    return tuple(sorted(records))


def duplicate_route_rules(flask_app):
    registrations = defaultdict(list)

    for route in registered_routes(flask_app):
        registrations[route.rule].append(route)

    duplicates = {}

    for rule, records in registrations.items():
        has_overlap = any(
            set(left.methods).intersection(right.methods)
            for index, left in enumerate(records)
            for right in records[index + 1:]
        )

        if has_overlap:
            duplicates[rule] = tuple(records)

    return duplicates


def format_route_catalog(flask_app):
    grouped = defaultdict(list)

    for route in registered_routes(flask_app):
        grouped[route.section].append(route)

    lines = []

    for section in sorted(grouped):
        lines.append(section)

        for route in grouped[section]:
            methods = ",".join(route.methods)
            lines.append(
                f"  {methods:<10} {route.rule:<72} "
                f"{route.endpoint}"
            )

    route_count = sum(
        len(records)
        for records in grouped.values()
    )
    lines.append("")
    lines.append(f"Total routes: {route_count}")

    duplicates = duplicate_route_rules(flask_app)

    if duplicates:
        lines.append("Overlapping route registrations:")

        for rule, records in sorted(duplicates.items()):
            endpoints = ", ".join(
                route.endpoint
                for route in records
            )
            lines.append(f"  {rule}: {endpoints}")
    else:
        lines.append(
            "Overlapping route registrations: none"
        )

    return "\n".join(lines)


def main():
    os.environ["JOB_SCHEDULER_ENABLED"] = "false"
    os.environ["JOB_LIFECYCLE_ENABLED"] = "false"

    from app import app

    print(format_route_catalog(app))
    return 1 if duplicate_route_rules(app) else 0


if __name__ == "__main__":
    raise SystemExit(main())
