
import csv

from models import JobSourceCompany


def export_lever_sources(filepath):
    sources = (
        JobSourceCompany.query
        .filter_by(source_type="lever")
        .order_by(JobSourceCompany.company_name.asc())
        .all()
    )

    with open(filepath, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)

        writer.writerow([
            "company_name",
            "source_type",
            "source_identifier",
            "careers_url",
            "is_active",
            "last_checked_at"
        ])

        for source in sources:
            writer.writerow([
                source.company_name,
                source.source_type,
                source.source_identifier,
                source.careers_url,
                source.is_active,
                source.last_checked_at
            ])
            
            