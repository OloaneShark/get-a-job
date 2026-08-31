import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

from models import JOB_APPLICATION_STRING_LIMITS


TABLE_NAME = "job_application"
MIGRATED_COLUMNS = (
    "company_name",
    "position_title",
    "company_website",
    "job_posting_url",
    "recruiter_email",
    "salary",
    "location",
)


load_dotenv()

database_url = os.getenv("DATABASE_URL")

if not database_url:
    raise RuntimeError("DATABASE_URL is not set.")

engine = create_engine(
    database_url,
    pool_pre_ping=True,
)


with engine.begin() as connection:
    inspector = inspect(connection)

    if not inspector.has_table(TABLE_NAME):
        raise RuntimeError(
            f'Table "{TABLE_NAME}" does not exist.'
        )

    existing_columns = {
        column["name"]: column
        for column in inspector.get_columns(TABLE_NAME)
    }

    dialect_name = connection.dialect.name
    quote = connection.dialect.identifier_preparer.quote

    for column_name in MIGRATED_COLUMNS:
        column = existing_columns.get(column_name)

        if column is None:
            raise RuntimeError(
                f'{TABLE_NAME}.{column_name} does not exist.'
            )

        target_length = JOB_APPLICATION_STRING_LIMITS[
            column_name
        ]
        current_length = getattr(
            column["type"],
            "length",
            None,
        )

        if current_length is None:
            print(
                f"{TABLE_NAME}.{column_name} is already unbounded."
            )
            continue

        if current_length >= target_length:
            print(
                f"{TABLE_NAME}.{column_name} already allows "
                f"{current_length} characters."
            )
            continue

        if dialect_name == "sqlite":
            print(
                f"SQLite does not enforce the declared length for "
                f"{TABLE_NAME}.{column_name}; no ALTER is required."
            )
            continue

        if dialect_name != "postgresql":
            raise RuntimeError(
                "This migration currently supports PostgreSQL and "
                "SQLite only."
            )

        connection.execute(
            text(
                f"ALTER TABLE {quote(TABLE_NAME)} "
                f"ALTER COLUMN {quote(column_name)} "
                f"TYPE VARCHAR({target_length})"
            )
        )

        print(
            f"Widened {TABLE_NAME}.{column_name} from "
            f"{current_length} to {target_length} characters."
        )


print("Job application capacity migration complete.")
