FROM apache/airflow:3.3.2

USER airflow

# Pipeline code (pandas, SQLAlchemy, dbt, ...) lives in its own virtualenv so its
# dependencies can never conflict with the ones Airflow itself pins.
COPY pipeline-requirements.txt /tmp/pipeline-requirements.txt
RUN python -m venv /home/airflow/pipeline-venv && /home/airflow/pipeline-venv/bin/pip install --no-cache-dir --upgrade pip && /home/airflow/pipeline-venv/bin/pip install --no-cache-dir -r /tmp/pipeline-requirements.txt
