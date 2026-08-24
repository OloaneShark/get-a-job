
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text


load_dotenv()

database_url = os.getenv(
    "DATABASE_URL"
)

if not database_url:
    raise RuntimeError(
        "DATABASE_URL is not set."
    )


engine = create_engine(
    database_url,
    pool_pre_ping=True,
)


def add_column_if_missing(
    connection,
    table_name,
    columns,
    name,
    definition,
):
    if name in columns:
        print(
            f"{table_name}.{name} already exists."
        )
        return

    connection.execute(
        text(
            f'ALTER TABLE "{table_name}" '
            f'ADD COLUMN {name} {definition}'
        )
    )

    columns.add(
        name
    )

    print(
        f"Added {table_name}.{name}."
    )


with engine.begin() as connection:
    inspector = inspect(
        connection
    )

    columns = {
        item["name"]
        for item in inspector.get_columns(
            "applicant_profile"
        )
    }

    add_column_if_missing(
        connection,
        "applicant_profile",
        columns,
        "is_18_or_older",
        "VARCHAR(20) NOT NULL DEFAULT 'Unknown'",
    )
    add_column_if_missing(
        connection,
        "applicant_profile",
        columns,
        "work_authorization_default",
        "VARCHAR(20) NOT NULL DEFAULT 'Unknown'",
    )
    add_column_if_missing(
        connection,
        "applicant_profile",
        columns,
        "sponsorship_default",
        "VARCHAR(20) NOT NULL DEFAULT 'Unknown'",
    )
    add_column_if_missing(
        connection,
        "applicant_profile",
        columns,
        "willing_to_relocate",
        "VARCHAR(20) NOT NULL DEFAULT 'Unknown'",
    )
    add_column_if_missing(
        connection,
        "applicant_profile",
        columns,
        "willing_to_travel",
        "VARCHAR(20) NOT NULL DEFAULT 'Unknown'",
    )
    add_column_if_missing(
        connection,
        "applicant_profile",
        columns,
        "years_of_experience",
        "INTEGER",
    )
    add_column_if_missing(
        connection,
        "applicant_profile",
        columns,
        "salary_expectation",
        "VARCHAR(100)",
    )
    add_column_if_missing(
        connection,
        "applicant_profile",
        columns,
        "available_start_date",
        "DATE",
    )


print(
    "Application answer profile migration complete."
)
