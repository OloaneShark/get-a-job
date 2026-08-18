
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

from models import EmailVerificationCode, TwoFactorRecoveryCode


load_dotenv()

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is not set.")

engine = create_engine(database_url, pool_pre_ping=True)


def add_column_if_missing(
    connection,
    table_name,
    existing_columns,
    column_name,
    definition,
):
    if column_name in existing_columns:
        print(f"{table_name}.{column_name} already exists.")
        return False

    connection.execute(
        text(
            f'ALTER TABLE "{table_name}" '
            f'ADD COLUMN {column_name} {definition}'
        )
    )
    existing_columns.add(column_name)
    print(f"Added {table_name}.{column_name}.")
    return True


with engine.begin() as connection:
    inspector = inspect(connection)
    if "user" not in set(inspector.get_table_names()):
        raise RuntimeError('The "user" table does not exist.')

    columns = {
        column["name"]
        for column in inspector.get_columns("user")
    }

    dialect = engine.dialect.name
    boolean_false = (
        "BOOLEAN NOT NULL DEFAULT FALSE"
        if dialect == "postgresql"
        else "BOOLEAN NOT NULL DEFAULT 0"
    )

    email_added = add_column_if_missing(
        connection,
        "user",
        columns,
        "email_verified",
        boolean_false,
    )
    add_column_if_missing(
        connection,
        "user",
        columns,
        "profile_image",
        "VARCHAR(255)",
    )
    add_column_if_missing(
        connection,
        "user",
        columns,
        "two_factor_enabled",
        boolean_false,
    )
    add_column_if_missing(
        connection,
        "user",
        columns,
        "totp_secret",
        "TEXT",
    )
    add_column_if_missing(
        connection,
        "user",
        columns,
        "pending_totp_secret",
        "TEXT",
    )

    if email_added:
        if dialect == "postgresql":
            connection.execute(
                text('UPDATE "user" SET email_verified = TRUE')
            )
        else:
            connection.execute(
                text('UPDATE "user" SET email_verified = 1')
            )
        print("Marked existing accounts as verified.")

    # Google only returns to the app after email_verified is true.
    if dialect == "postgresql":
        connection.execute(
            text(
                'UPDATE "user" SET email_verified = TRUE '
                'WHERE google_sub IS NOT NULL'
            )
        )
    else:
        connection.execute(
            text(
                'UPDATE "user" SET email_verified = 1 '
                'WHERE google_sub IS NOT NULL'
            )
        )


EmailVerificationCode.__table__.create(bind=engine, checkfirst=True)
TwoFactorRecoveryCode.__table__.create(bind=engine, checkfirst=True)

print("Account-security schema migration complete.")
