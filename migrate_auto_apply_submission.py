
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from models import ApplicantProfile, ApplicationSubmissionAttempt

load_dotenv()
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is not set.")
engine = create_engine(database_url, pool_pre_ping=True)


def add_column_if_missing(connection, table_name, columns, name, definition):
    if name in columns:
        print(f"{table_name}.{name} already exists.")
        return
    connection.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN {name} {definition}'))
    columns.add(name)
    print(f"Added {table_name}.{name}.")


ApplicantProfile.__table__.create(bind=engine, checkfirst=True)
ApplicationSubmissionAttempt.__table__.create(bind=engine, checkfirst=True)

with engine.begin() as connection:
    inspector = inspect(connection)
    candidate_columns = {item["name"] for item in inspector.get_columns("auto_apply_candidate")}
    add_column_if_missing(connection, "auto_apply_candidate", candidate_columns, "application_id", "INTEGER")
    add_column_if_missing(connection, "auto_apply_candidate", candidate_columns, "application_package_id", "INTEGER")
    add_column_if_missing(connection, "auto_apply_candidate", candidate_columns, "execution_status", "VARCHAR(40) NOT NULL DEFAULT 'Not Started'")
    add_column_if_missing(connection, "auto_apply_candidate", candidate_columns, "last_submission_attempt_at", "TIMESTAMP")

    package_columns = {item["name"] for item in inspector.get_columns("application_package")}
    add_column_if_missing(connection, "application_package", package_columns, "application_email", "VARCHAR(255)")
    add_column_if_missing(connection, "application_package", package_columns, "discovered_job_id", "INTEGER")
    add_column_if_missing(connection, "application_package", package_columns, "job_snapshot_json", "TEXT")

print("Auto Apply submission migration complete.")
