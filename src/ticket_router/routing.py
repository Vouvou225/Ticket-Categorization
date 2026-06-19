"""
Routing configuration. The file you edit most.

Everything that decides where a ticket goes lives here: the category taxonomy
the model may choose from, the map from category to ServiceNow assignment
group, the map from model priority to ServiceNow impact/urgency, and the
confidence threshold below which a ticket is handed to humans.

The three categories below come from the original notebook and are deliberately
minimal. Add your real categories and paste the matching assignment group
sys_ids from your ServiceNow instance (the sys_user_group table). The model can
only choose categories that exist in the Category enum.
"""

from dataclasses import dataclass
from enum import StrEnum


class Category(StrEnum):
    # Values match the `category` column in the ServiceNow source exactly, so
    # predictions can be scored directly against what a person chose. These are
    # the high-volume categories; the long tail of low-count and malformed
    # values (for example "[object Object]") folds into OTHER.
    APPLICATION = "application"
    HARDWARE = "hardwares"
    NETWORKING = "networking"
    SERVERS = "servers"
    TELECOMMUNICATIONS = "telecommunications"
    DATABASES = "databases"
    FACILITIES = "facilities"
    OTHER = "Other-CSM"


class Priority(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class ETA(StrEnum):
    ASAP = "ASAP"
    H2_4 = "Within 2-4 hours"
    H24 = "Within 24 hours"
    H48 = "Within 48 hours"


# Category -> ServiceNow assignment group sys_id. Replace the placeholders with
# real 32-char sys_ids. Until you do, tickets fall through to the triage group.
ASSIGNMENT_GROUPS: dict[Category, str] = {
    Category.APPLICATION: "REPLACE_WITH_APPLICATION_GROUP_SYS_ID",
    Category.HARDWARE: "REPLACE_WITH_HARDWARE_GROUP_SYS_ID",
    Category.NETWORKING: "REPLACE_WITH_NETWORKING_GROUP_SYS_ID",
    Category.SERVERS: "REPLACE_WITH_SERVERS_GROUP_SYS_ID",
    Category.TELECOMMUNICATIONS: "REPLACE_WITH_TELECOM_GROUP_SYS_ID",
    Category.DATABASES: "REPLACE_WITH_DATABASES_GROUP_SYS_ID",
    Category.FACILITIES: "REPLACE_WITH_FACILITIES_GROUP_SYS_ID",
    Category.OTHER: "REPLACE_WITH_OTHER_GROUP_SYS_ID",
}

# Where low-confidence or unmapped tickets go for a human to triage.
TRIAGE_GROUP_SYS_ID = "REPLACE_WITH_SERVICE_DESK_TRIAGE_GROUP_SYS_ID"

# ServiceNow derives priority from impact x urgency, so we set those (1 high .. 3).
PRIORITY_MAP: dict[Priority, dict[str, str]] = {
    Priority.HIGH: {"impact": "2", "urgency": "1"},
    Priority.MEDIUM: {"impact": "2", "urgency": "2"},
    Priority.LOW: {"impact": "3", "urgency": "3"},
}

# Below this confidence, do not auto-assign. Send to triage with a work note.
# This confidence bucketing pattern keeps low-certainty decisions with a human.
CONFIDENCE_THRESHOLD = 0.70


@dataclass(frozen=True)
class RouteDecision:
    assignment_group: str
    impact: str
    urgency: str
    auto_routed: bool
    reason: str


def _is_placeholder(group: str | None) -> bool:
    return not group or group.startswith("REPLACE_WITH")


def triage_fallback(reason: str) -> RouteDecision:
    """Decision used when classification fails. Send to triage, never drop the ticket."""
    return RouteDecision(
        assignment_group=TRIAGE_GROUP_SYS_ID,
        impact=PRIORITY_MAP[Priority.MEDIUM]["impact"],
        urgency=PRIORITY_MAP[Priority.MEDIUM]["urgency"],
        auto_routed=False,
        reason=reason,
    )


def decide_route(category: Category, priority: Priority, confidence: float) -> RouteDecision:
    """Turn a model classification into a concrete ServiceNow assignment."""
    impact = PRIORITY_MAP[priority]["impact"]
    urgency = PRIORITY_MAP[priority]["urgency"]

    if confidence < CONFIDENCE_THRESHOLD:
        return RouteDecision(
            assignment_group=TRIAGE_GROUP_SYS_ID,
            impact=impact,
            urgency=urgency,
            auto_routed=False,
            reason=f"confidence {confidence:.2f} below threshold {CONFIDENCE_THRESHOLD}",
        )

    group = ASSIGNMENT_GROUPS.get(category)
    if _is_placeholder(group):
        return RouteDecision(
            assignment_group=TRIAGE_GROUP_SYS_ID,
            impact=impact,
            urgency=urgency,
            auto_routed=False,
            reason=f"no assignment group configured for category '{category.value}'",
        )

    return RouteDecision(
        assignment_group=group,  # type: ignore[arg-type]
        impact=impact,
        urgency=urgency,
        auto_routed=True,
        reason=f"routed on category '{category.value}' at confidence {confidence:.2f}",
    )
