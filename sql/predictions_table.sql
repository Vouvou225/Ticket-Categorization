-- Predictions table written by the batch runner.
-- The batch runner creates this automatically, but here is the explicit DDL.
-- Lives in a sandbox dataset you own, separate from the read-only source.

CREATE TABLE IF NOT EXISTS `omes-datascience-sbx.Ticket_Categorization.ticket_router_predictions` (
  sys_id                 STRING,
  number                 STRING,
  predicted_category     STRING,
  confidence             FLOAT64,
  priority               STRING,
  eta                    STRING,
  tags                   ARRAY<STRING>,
  assignment_group       STRING,
  auto_routed            BOOL,
  reason                 STRING,
  human_category         STRING,    -- what a person actually chose, for scoring
  human_assignment_group STRING,
  category_match         BOOL,      -- predicted == human (case-insensitive)
  ticket_excerpt         STRING,    -- redacted
  model                  STRING,
  predicted_at           TIMESTAMP
)
PARTITION BY DATE(predicted_at)
OPTIONS (
  description = "AI ticket router predictions, one row per classified incident."
);

-- Accuracy once your Category enum matches ServiceNow's category values:
--
-- SELECT
--   COUNT(*) AS scored,
--   ROUND(AVG(CAST(category_match AS INT64)), 4) AS match_rate,
--   ROUND(AVG(confidence), 3) AS avg_confidence
-- FROM `omes-datascience-sbx.Ticket_Categorization.ticket_router_predictions`
-- WHERE human_category IS NOT NULL;
