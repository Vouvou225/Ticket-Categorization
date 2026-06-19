# Production readiness and roadmap

This document states clearly what is built and verified, what configuration a deploying team supplies, how to roll it out safely, and what is planned before running it as critical infrastructure at scale. Knowing the difference between "works" and "production at scale" is part of the design.

## Built and verified

- One structured Gemini call on Vertex AI with schema-enforced output. No hand-written parsing.
- Routing layer mapping category to assignment group and priority to impact and urgency, with a confidence gate to a human triage queue.
- Suggest and enforce modes. Suggest writes the AI recommendation as a work note and changes nothing, so the service can run live and be measured before it is trusted.
- Fail-safe routing. A classification or quota error still sends the ticket to triage with a note. No ticket is dropped.
- Idempotency and human-override guard. Tickets already assigned are skipped, so the router never double-processes or overwrites manual work.
- PII redaction for the model prompt (optional) and the audit excerpt (default on).
- Async clients with retries on transient failures only.
- Structured JSON logging with request ids, shared-secret endpoint auth, and a BigQuery audit trail.
- 51 tests at 96% coverage, type checking, linting, CI, a hardened non-root container, and a Cloud Run deploy pipeline.

## Configuration supplied at deploy time

- Real categories in the `Category` enum and real assignment group sys_ids in `routing.py`. Until those are set, every ticket safely falls through to triage.
- The BigQuery audit table from `sql/audit_table.sql`.
- `WEBHOOK_TOKEN`, ServiceNow credentials in Secret Manager, and the GCP service account roles (`aiplatform.user`, `bigquery.dataEditor`).
- The ServiceNow trigger that calls the webhook, from the template in `servicenow/business_rule.example.js`.

## Rollout plan

1. Deploy with `ROUTING_MODE=suggest` and connect the webhook.
2. Run on live tickets for two to four weeks. The service only adds work notes during this phase.
3. Label a sample and run `scripts/evaluate.py` to measure per-category accuracy and, most importantly, accuracy on the tickets that clear the confidence threshold (the ones enforce mode would auto-assign).
4. Tune `CONFIDENCE_THRESHOLD` to the precision the desk wants, then switch to `ROUTING_MODE=enforce`.
5. Keep watching the audit table and re-tune from real data.

## Roadmap for scale

These are deliberate next steps, sized to the deployment, not defects in the build.

- **Durable event delivery.** The webhook is synchronous today. For high volume or strict delivery guarantees, place Pub/Sub between ServiceNow and the service so events survive downtime and are retried. This is the first hardening step before high-volume enforce mode.
- **OAuth for ServiceNow.** Basic auth works; most production instances should move to OAuth. Only the client construction in `servicenow.py` changes.
- **Load and quota testing.** Vertex AI has per-project quota. Test at expected peak and request quota or add a concurrency limit as needed.
- **Alerting.** Cloud Run provides latency and error-rate metrics and the audit table provides business metrics. Add alerts on error rate and on a spike in the low-confidence triage rate.
- **Prompt-injection hardening.** Ticket text is untrusted input to an LLM. For routing the blast radius is small and is caught by the confidence gate and suggest mode, but this should be revisited if the model is ever given the ability to take actions.
- **Formal data-governance review.** Confirm that sending ticket text to Vertex AI and storing excerpts in BigQuery meets the organization's data handling rules. Redaction helps but does not replace that review.
