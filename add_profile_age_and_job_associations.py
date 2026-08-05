
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text


load_dotenv()

database_url = os.getenv("DATABASE_URL")

if not database_url:
    raise RuntimeError("DATABASE_URL is not set.")

engine = create_engine(database_url)
inspector = inspect(engine)

profile_columns = {
    column["name"]
    for column in inspector.get_columns(
        "job_search_profile"
    )
}

with engine.begin() as connection:
    if "maximum_posting_age_days" not in profile_columns:
        connection.execute(
            text(
                "ALTER TABLE job_search_profile "
                "ADD COLUMN maximum_posting_age_days "
                "INTEGER NOT NULL DEFAULT 395"
            )
        )

        print(
            "Added maximum_posting_age_days "
            "with the default: 395."
        )
    else:
        print(
            "maximum_posting_age_days already exists."
        )

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "discovered_job_profile" not in table_names:
        connection.execute(
            text(
                "CREATE TABLE discovered_job_profile ("
                "discovered_job_id INTEGER NOT NULL, "
                "search_profile_id INTEGER NOT NULL, "
                "PRIMARY KEY "
                "(discovered_job_id, search_profile_id), "
                "FOREIGN KEY(discovered_job_id) "
                "REFERENCES discovered_job (id) "
                "ON DELETE CASCADE, "
                "FOREIGN KEY(search_profile_id) "
                "REFERENCES job_search_profile (id) "
                "ON DELETE CASCADE"
                ")"
            )
        )

        print("Created discovered_job_profile.")
    else:
        print("discovered_job_profile already exists.")

    connection.execute(
        text(
            "INSERT INTO discovered_job_profile "
            "(discovered_job_id, search_profile_id) "
            "SELECT id, search_profile_id "
            "FROM discovered_job "
            "WHERE search_profile_id IS NOT NULL "
            "ON CONFLICT DO NOTHING"
        )
    )

    print(
        "Backfilled existing discovered-job "
        "profile associations."
    )
