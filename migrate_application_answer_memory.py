
from app import app
from models import ApplicationAnswerMemory, db


def main():
    print("=" * 88)
    print("JOBFINITUM - APPLICATION ANSWER MEMORY MIGRATION")
    print("=" * 88)

    with app.app_context():
        inspector = db.inspect(db.engine)

        if (
            "application_answer_memory"
            in inspector.get_table_names()
        ):
            print("EXISTS  | application_answer_memory")
            print("No migration needed.")
            return

        ApplicationAnswerMemory.__table__.create(
            bind=db.engine
        )

        print("CREATED | application_answer_memory")
        print("Migration complete.")


if __name__ == "__main__":
    main()
