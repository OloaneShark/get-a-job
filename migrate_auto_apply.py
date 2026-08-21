
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

from models import AutoApplyCandidate

load_dotenv()

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is not set.")

engine = create_engine(database_url, pool_pre_ping=True)


def add_column_if_missing(connection, columns, name, definition):
    if name in columns:
        print(f"job_search_profile.{name} already exists.")
        return
    connection.execute(text(
        'ALTER TABLE "job_search_profile" '
        f'ADD COLUMN {name} {definition}'
    ))
    columns.add(name)
    print(f"Added job_search_profile.{name}.")


with engine.begin() as connection:
    inspector = inspect(connection)
    if "job_search_profile" not in set(inspector.get_table_names()):
        raise RuntimeError("The job_search_profile table does not exist.")

    columns = {
        column["name"]
        for column in inspector.get_columns("job_search_profile")
    }
    boolean_false = (
        "BOOLEAN NOT NULL DEFAULT FALSE"
        if engine.dialect.name == "postgresql"
        else "BOOLEAN NOT NULL DEFAULT 0"
    )

    add_column_if_missing(connection, columns, "auto_apply_enabled", boolean_false)
    add_column_if_missing(connection, columns, "auto_apply_resume_id", "INTEGER")
    add_column_if_missing(
        connection,
        columns,
        "auto_apply_cover_letter_mode",
        "VARCHAR(30) NOT NULL DEFAULT 'when_required'",
    )
    add_column_if_missing(connection, columns, "auto_apply_excluded_companies", "TEXT")
    add_column_if_missing(connection, columns, "auto_apply_daily_limit", "INTEGER NOT NULL DEFAULT 10")
    add_column_if_missing(connection, columns, "auto_apply_contact_email", "VARCHAR(255)")

AutoApplyCandidate.__table__.create(bind=engine, checkfirst=True)

with engine.begin() as connection:
    inspector = inspect(connection)

    candidate_columns = {
        column["name"]
        for column in inspector.get_columns(
            "auto_apply_candidate"
        )
    }

    if "application_email" not in candidate_columns:
        connection.execute(
            text(
                'ALTER TABLE "auto_apply_candidate" '
                'ADD COLUMN application_email VARCHAR(255)'
            )
        )
        print(
            "Added auto_apply_candidate.application_email."
        )
    else:
        print(
            "auto_apply_candidate.application_email "
            "already exists."
        )

    if engine.dialect.name == "postgresql":
        connection.execute(
            text(
                'UPDATE auto_apply_candidate AS candidate '
                'SET application_email = "user".email '
                'FROM "user" '
                'WHERE candidate.user_id = "user".id '
                'AND candidate.application_email IS NULL'
            )
        )
    else:
        connection.execute(
            text(
                'UPDATE auto_apply_candidate '
                'SET application_email = ('
                'SELECT email FROM "user" '
                'WHERE "user".id = auto_apply_candidate.user_id'
                ') '
                'WHERE application_email IS NULL'
            )
        )

print("Auto Apply foundation schema migration complete.")
print("Auto Apply application-email migration complete.")
