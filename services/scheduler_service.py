
from apscheduler.schedulers.background import BackgroundScheduler


scheduler = BackgroundScheduler()


def scheduler_test_job():
    print("SCHEDULER TEST: background job is running.")


def start_scheduler():
    scheduler.add_job(
        scheduler_test_job,
        "interval",
        minutes=1,
        id="scheduler_test_job",
        replace_existing=True
    )

    scheduler.start()
    