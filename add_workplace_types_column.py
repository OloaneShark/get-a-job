
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text


load_dotenv()

database_url = os.getenv("DATABASE_URL")

if not database_url:
    raise RuntimeError("DATABASE_URL is not set.")

engine = create_engine(database_url)

inspector = inspect(engine)

column_names = {
    column["name"]
    for column in inspector.get_columns(
        "job_search_profile"
    )
}

if "workplace_types" in column_names:
    print(
        "workplace_types already exists. "
        "No migration was needed."
    )
else:
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE job_search_profile "
                "ADD COLUMN workplace_types "
                "TEXT NOT NULL DEFAULT 'remote'"
            )
        )

    print(
        "Added workplace_types with the "
        "legacy-safe default: remote."
    )
