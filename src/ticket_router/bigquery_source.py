"""
BigQuery incident source.

Reads a batch of incidents from the ServiceNow mirror table in BigQuery. This
is strictly read-only: it runs a SELECT and never writes to the source. It pulls
only the columns the router needs, plus the human-entered category and
assignment group so predictions can be scored against what a person actually
chose.
"""

from ticket_router.config import Settings
from ticket_router.logging_config import get_logger

logger = get_logger(__name__)


class IncidentSource:
    def __init__(self, settings: Settings):
        from google.cloud import bigquery

        self._bq = bigquery
        self._client = bigquery.Client(project=settings.google_cloud_project)
        self._table = settings.incident_source_table
        self._settings = settings

    def fetch_recent(self, limit: int) -> list[dict]:
        """Return the most recent incidents that have ticket text."""
        query = f"""
            SELECT
                sys_id,
                number,
                short_description,
                description,
                category AS human_category,
                subcategory AS human_subcategory,
                assignment_group AS human_assignment_group,
                priority AS human_priority
            FROM `{self._table}`
            WHERE TRIM(COALESCE(description, short_description, '')) != ''
            ORDER BY sys_created_on DESC
            LIMIT @limit
        """
        job_config = self._bq.QueryJobConfig(
            query_parameters=[self._bq.ScalarQueryParameter("limit", "INT64", limit)],
            # Hard cost cap: if a query would scan more than this, it fails
            # before running instead of billing. A single pull of this table
            # scans well under 1 GB, so 5 GB is a generous safety ceiling that
            # still makes a runaway scan impossible.
            maximum_bytes_billed=self._settings.max_bytes_billed,
        )
        rows = self._client.query(query, job_config=job_config).result()
        incidents = [dict(row) for row in rows]
        logger.info("fetched incidents", extra={"fields": {"count": len(incidents)}})
        return incidents
