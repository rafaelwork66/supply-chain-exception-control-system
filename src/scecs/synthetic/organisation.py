"""Synthetic organisation and reference-data generation."""

from __future__ import annotations

from scecs.synthetic._util import stable_id, timestamp_for
from scecs.synthetic.config import SyntheticGeneratorConfig
from scecs.synthetic.types import DatasetMap, Record


def generate_organisation(config: SyntheticGeneratorConfig) -> DatasetMap:
    """Generate sites, simulated users, ownership mappings, calendar and rule metadata."""

    active_from = timestamp_for(config.history_start)
    site_templates = [
        ("MEL-DC", "Melbourne Distribution Centre", "VIC"),
        ("GEEL-MFG", "Geelong Manufacturing Support", "VIC"),
    ]
    sites: list[Record] = [
        {
            "id": stable_id(config, "site", code),
            "site_code": code,
            "site_name": name,
            "state_code": state,
            "timezone_name": config.timezone_name,
            "active_from": active_from,
            "active_to": "",
            "synthetic_data_flag": "true",
        }
        for code, name, state in site_templates[: config.site_count]
    ]

    role_counts = [("buyer", 8), ("planner", 6), ("supply_chain_manager", 3), ("data_quality_analyst", 2)]
    users: list[dict[str, object]] = []
    for role, count in role_counts:
        for index in range(1, count + 1):
            code = f"{role.upper()}-{index:02d}"
            users.append(
                {
                    "id": stable_id(config, "user", code),
                    "user_code": code,
                    "display_name": f"Synthetic {role.replace('_', ' ').title()} {index:02d}",
                    "role_classification": role,
                    "actor_type": "human",
                    "active_from": active_from,
                    "active_to": "",
                    "synthetic_data_flag": "true",
                }
            )
    for queue in ("PROCUREMENT_QUEUE", "PLANNING_QUEUE"):
        users.append(
            {
                "id": stable_id(config, "user", queue),
                "user_code": queue,
                "display_name": f"Synthetic {queue.replace('_', ' ').title()}",
                "role_classification": "queue",
                "actor_type": "queue",
                "active_from": active_from,
                "active_to": "",
                "synthetic_data_flag": "true",
            }
        )

    ownership_mappings: list[dict[str, object]] = []
    scopes = ("supplier_site", "buyer_group_site", "category_site", "duty_queue")
    for site in sites:
        for precedence, scope in enumerate(scopes, start=1):
            owner = users[(precedence + len(ownership_mappings)) % len(users)]
            key = f"{site['site_code']}:{scope}"
            ownership_mappings.append(
                {
                    "id": stable_id(config, "ownership_mapping", key),
                    "precedence": precedence,
                    "scope_type": scope,
                    "scope_key": key,
                    "site_id": site["id"],
                    "owner_user_id": owner["id"] if owner["actor_type"] == "human" else "",
                    "owner_queue_code": owner["user_code"] if owner["actor_type"] == "queue" else "",
                    "approval_reference": "SYNTHETIC-GOVERNED-OWNERSHIP-V1",
                    "evidence_reference": "synthetic://ownership/default",
                    "effective_from": active_from,
                    "effective_to": "",
                    "synthetic_data_flag": "true",
                }
            )

    calendar_versions: list[Record] = [
        {
            "id": stable_id(config, "calendar_version", "MEL-BUSINESS-1.0"),
            "calendar_code": "MEL_BUSINESS",
            "version": "1.0",
            "timezone_name": config.timezone_name,
            "business_hours": '{"mon-fri":"08:30-17:00"}',
            "holiday_set": '{"jurisdiction":"VIC","synthetic":true}',
            "approved_at": timestamp_for(config.history_start, 8, 30),
        }
    ]
    rule_versions: list[Record] = [
        {
            "id": stable_id(config, "rule_version", "RPR-REFERENCE-ONLY-1.0.0"),
            "rule_code": "RPR_REFERENCE_ONLY",
            "version": "1.0.0",
            "status": "approved",
            "owner": "Synthetic Governance",
            "rationale": "Reference metadata only; no scoring implemented by synthetic generator.",
            "approved_at": timestamp_for(config.history_start, 8, 30),
            "effective_from": timestamp_for(config.history_start, 8, 30),
            "effective_to": "",
        }
    ]
    return {
        "sites": sites,
        "users": users,
        "ownership_mappings": ownership_mappings,
        "calendar_versions": calendar_versions,
        "rule_versions": rule_versions,
    }
