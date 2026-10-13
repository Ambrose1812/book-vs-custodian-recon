"""Phase 1 pipeline: ingest -> land as Parquet -> load to Postgres -> dbt build -> dbt test.

Every task shells out to the same scripts and dbt commands you run by hand, inside an
isolated virtualenv, so a DAG run and a manual run behave identically.

Order matters because of real data dependencies:
  * Tiingo prices and simulated transactions need marts.dim_security_master, which
    needs OpenFIGI loaded and the security-master models built first.
  * Everything downstream of the loads needs raw tables to exist.

Safe to re-run: the loader replaces whole ingest_date partitions inside one
transaction, guards itself with a Postgres advisory lock, and the staging models keep
only the latest ingest of each record. Triggered manually for now (schedule=None).
"""

from datetime import datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

PROJECT = "/opt/airflow/project"
DBT_DIR = f"{PROJECT}/dbt/recon_dbt"
PY = "/home/airflow/pipeline-venv/bin/python"
DBT = "/home/airflow/pipeline-venv/bin/dbt"


def python_script(task_id: str, script: str, **kwargs) -> BashOperator:
    return BashOperator(
        task_id=task_id,
        bash_command=f"cd {PROJECT} && {PY} ingest/{script}",
        **kwargs,
    )


def dbt_command(task_id: str, args: str, **kwargs) -> BashOperator:
    return BashOperator(
        task_id=task_id,
        bash_command=f"cd {DBT_DIR} && {DBT} deps && {DBT} {args}",
        **kwargs,
    )


# The simulated transactions are random, so they are generated once and kept.
# Regenerating them on every run would silently replace the book of record.
SEED_ONCE = (
    f"cd {PROJECT} && "
    'if [ -n "$(ls -A data/landing/transactions 2>/dev/null)" ]; then '
    'echo "Simulated transactions already seeded; skipping."; '
    f"else {PY} ingest/simulate_transactions.py; fi"
)

with DAG(
    dag_id="recon_pipeline",
    description="Book-vs-custodian reconciliation: Phase 1 batch pipeline",
    start_date=datetime(2026, 10, 1),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=2)},
    tags=["recon", "phase1"],
) as dag:
    ingest_openfigi = python_script("ingest_openfigi", "openfigi_ingest.py")
    load_reference = python_script("load_reference_data", "load_to_postgres.py")
    build_security_master = dbt_command(
        "build_security_master",
        "run --select stg_openfigi_mappings dim_security_master",
    )

    seed_transactions = BashOperator(
        task_id="seed_simulated_transactions", bash_command=SEED_ONCE
    )
    # Tiingo's free tier allows 50 requests/hour: a quick retry would only burn the quota.
    ingest_tiingo = python_script("ingest_tiingo", "tiingo_ingest.py", retries=0)

    load_all = python_script("load_all_raw", "load_to_postgres.py")
    dbt_run = dbt_command("dbt_run", "run")
    dbt_test = dbt_command("dbt_test", "test")

    ingest_openfigi >> load_reference >> build_security_master
    build_security_master >> [seed_transactions, ingest_tiingo] >> load_all
    load_all >> dbt_run >> dbt_test
