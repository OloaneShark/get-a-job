
FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

COPY . .

EXPOSE 5000

CMD ["sh", "-c", "python migrate_account_security.py && python migrate_shared_job_cache.py && python migrate_auto_apply.py && python migrate_auto_apply_submission.py && exec gunicorn --bind 0.0.0.0:5000 app:app"]
