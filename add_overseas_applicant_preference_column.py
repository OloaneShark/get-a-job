
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text


load_dotenv()

database_url = os.getenv("DATABASE_URL")

if not database_url:
    raise RuntimeError("DATABASE_URL is not set.")

engine = create_engine(database_url)
inspector = inspect(engine)

column_name = "overseas_applicant_preference"

column_names = {
    column["name"]
    for column in inspector.get_columns(
        "job_search_profile"
    )
}

if column_name in column_names:
    print(
        f"{column_name} already exists. "
        "No migration was needed."
    )
else:
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE job_search_profile "
                "ADD COLUMN "
                "overseas_applicant_preference "
                "VARCHAR(20) NOT NULL "
                "DEFAULT 'any'"
            )
        )

    print(
        "Added overseas_applicant_preference "
        "with the default: any."
    )
