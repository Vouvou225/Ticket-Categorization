-- Audit table for routing decisions.
-- Create the dataset and table once before enabling AUDIT_ENABLED=true.
--
--   bq mk --location=us-central1 help_desk
--   bq query --use_legacy_sql=false < sql/audit_table.sql
--
-- Partitioned by day so accuracy queries over recent windows stay cheap.

CREATE TABLE IF NOT EXISTS `help_desk.routing_decisions` (
  request_id        STRING    NOT NULL,
  occurred_at       TIMESTAMP NOT NULL,
  ticket_excerpt    STRING,
  category          STRING,
  confidence        FLOAT64,
  priority          STRING,
  eta               STRING,
  tags              ARRAY<STRING>,
  assignment_group  STRING,
  auto_routed       BOOL,
  reason            STRING,
  servicenow_sys_id STRING,
  servicenow_number STRING
)
PARTITION BY DATE(occurred_at)
OPTIONS (
  description = "One row per ticket routing decision from the help desk router."
);

-- Example: auto-route rate and average confidence by category, last 7 days.
--
-- SELECT
--   category,
--   COUNT(*) AS tickets,
--   AVG(confidence) AS avg_confidence,
--   SAFE_DIVIDE(COUNTIF(auto_routed), COUNT(*)) AS auto_route_rate
-- FROM `help_desk.routing_decisions`
-- WHERE occurred_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
-- GROUP BY category
-- ORDER BY tickets DESC;
