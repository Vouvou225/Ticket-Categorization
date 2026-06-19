"""
Predictions writer.

Writes one row per classified incident to a results table you own, separate
from the source. Creates the table (partitioned by prediction date) if it does
not exist, then appends each batch with a load job, which is free and handles
the repeated tags field cleanly.
"""

from ticket_router.config import Settings
from ticket_router.logging_config import get_logger

logger = get_logger(__name__)


class PredictionsWriter:
    def __init__(self, settings: Settings):
        from google.cloud import bigquery

        self._bq = bigquery
        self._client = bigquery.Client(project=settings.google_cloud_project)
        self._table = settings.predictions_table
        self._ensure_table()

    def _schema(self) -> list:
        bq = self._bq
        return [
            bq.SchemaField("sys_id", "STRING"),
            bq.SchemaField("number", "STRING"),
            bq.SchemaField("predicted_category", "STRING"),
            bq.SchemaField("confidence", "FLOAT"),
            bq.SchemaField("priority", "STRING"),
            bq.SchemaField("eta", "STRING"),
            bq.SchemaField("tags", "STRING", mode="REPEATED"),
            bq.SchemaField("assignment_group", "STRING"),
            bq.SchemaField("auto_routed", "BOOL"),
            bq.SchemaField("reason", "STRING"),
            bq.SchemaField("human_category", "STRING"),
            bq.SchemaField("human_assignment_group", "STRING"),
            bq.SchemaField("category_match", "BOOL"),
            bq.SchemaField("ticket_excerpt", "STRING"),
            bq.SchemaField("model", "STRING"),
            bq.SchemaField("predicted_at", "TIMESTAMP"),
        ]

    def _ensure_table(self) -> None:
        table = self._bq.Table(self._table, schema=self._schema())
        table.time_partitioning = self._bq.TimePartitioning(field="predicted_at")
        self._client.create_table(table, exists_ok=True)

    def write(self, rows: list[dict]) -> None:
        if not rows:
            return
        job_config = self._bq.LoadJobConfig(
            schema=self._schema(),
            write_disposition="WRITE_APPEND",
        )
        job = self._client.load_table_from_json(rows, self._table, job_config=job_config)
        job.result()
        logger.info("wrote predictions", extra={"fields": {"count": len(rows)}})
