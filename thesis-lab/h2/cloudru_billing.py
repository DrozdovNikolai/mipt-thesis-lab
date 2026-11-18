"""Bounded read-only Billing snapshots; missing data is never a zero charge."""
import math


class BillingUnavailable(ValueError):
    pass


def consumption(client, query):
    rows, pages = [], []
    for page in range(1, 21):
        page_query = {**query, "page_filter.page": page, "page_filter.limit": 100}
        response = client.request("organization", "/v1/consumption", page_query)
        batch = response.get("consumptions") if isinstance(response, dict) else None
        if not isinstance(batch, list):
            raise BillingUnavailable("Billing response has no consumption list")
        pages.append({"query": page_query, "response": response})
        rows.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise BillingUnavailable("Billing pagination exceeded 20 pages; snapshot is incomplete")
    try:
        amounts = [float(row["amount_nds"]) for row in rows if not row.get("is_delete")]
    except (KeyError, TypeError, ValueError, AttributeError):
        raise BillingUnavailable("Billing response has invalid amounts") from None
    if not all(math.isfinite(value) for value in amounts):
        raise BillingUnavailable("Billing response has non-finite amounts")
    return {"consumptions": rows, "pages": pages, "preliminary_rub": sum(amounts)}
