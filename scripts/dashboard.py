"""
Launch the stakeholder dashboard.

    python scripts/dashboard.py

Then open http://127.0.0.1:8000 in your browser. The scorecard and table read
from the predictions table in BigQuery, so run a batch first to populate it:

    python scripts/run_batch.py --limit 150

The simulator calls Vertex AI live. Needs GOOGLE_CLOUD_PROJECT set and ADC
configured. Binds to localhost only.
"""

import uvicorn


def main() -> None:
    uvicorn.run("ticket_router.dashboard:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
