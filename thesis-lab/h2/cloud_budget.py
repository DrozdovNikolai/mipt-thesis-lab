"""Separate a planning estimate from the owner's actual spending ceiling."""
import json
import math


def policy(cloud):
    path = cloud.run / "budget-policy.json"
    if path.exists():
        values = json.loads(path.read_text())
    else:
        default = getattr(cloud, "plan", {}).get("budget_rub", 500)
        values = {"planning_target_rub": default, "spending_ceiling_rub": default}
    result = {}
    for name in ("planning_target_rub", "spending_ceiling_rub"):
        value = values[name]
        if name == "spending_ceiling_rub" and value is None:
            result[name] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("Budget values must be finite positive RUB amounts")
        result[name] = value
    if result["spending_ceiling_rub"] is not None and result["spending_ceiling_rub"] < result["planning_target_rub"]:
        raise ValueError("Spending ceiling is below the planning estimate")
    return result
