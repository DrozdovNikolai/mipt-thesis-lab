"""Read-only Cloud.ru H2 inventory and price estimates; never provisions resources.

Uses the owner's local profile from cloudru_access.py. All HTTP methods are GET
except the documented, non-mutating Kubernetes price calculator. Authentication
tokens and credential values are excluded from the saved evidence.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from h2.cloudru_access import NoRedirect, authenticate, load_profile

ENDPOINTS = {
    "organization": "https://organization.api.cloud.ru",
    "compute": "https://compute.api.cloud.ru",
    "mk8s": "https://mk8s.api.cloud.ru",
    "iam": "https://iam.api.cloud.ru",
    "ar": "https://ar.api.cloud.ru",
    "nlb": "https://nlb.api.cloud.ru",
    "monitoring": "https://monitoring.api.cloud.ru",
}
QUOTE_PATH = "/v2/billing/calculate-price-ext"


class CloudruError(Exception):
    def __init__(self, service, status, detail):
        self.service, self.status, self.detail = service, status, detail
        super().__init__(f"{service}: HTTP {status}")


class ReadClient:
    def __init__(self, profile):
        self.project_id = profile["project_id"]
        self._token = authenticate(profile)
        self._secrets = (self._token, profile["key_id"], profile["key_secret"])

    def redact(self, value):
        if isinstance(value, dict):
            return {k: self.redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        if isinstance(value, str):
            for secret in self._secrets:
                value = value.replace(secret, "[REDACTED]")
        return value

    def request(self, service, path, query=None, *, method="GET", body=None):
        if service not in ENDPOINTS or not path.startswith("/") or "?" in path:
            raise ValueError("Use a named Cloud.ru service and an absolute API path")
        if method != "GET" and not (method == "POST" and service == "mk8s" and path == QUOTE_PATH):
            raise ValueError("This client permits only reads and the price calculator")
        if method == "GET" and body is not None:
            raise ValueError("GET requests cannot carry a body")
        url = ENDPOINTS[service] + path
        if query:
            # IAM's filter parser does not interpret '+' as a space.
            url += "?" + urllib.parse.urlencode(query, doseq=True, quote_via=urllib.parse.quote)
        req = urllib.request.Request(url, method=method,
            headers={"Authorization": "Bearer " + self._token,
                     "Content-Type": "application/json", "Accept": "application/json"},
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read(16384))
            except (ValueError, UnicodeError):
                detail = {"message": "Non-JSON error response omitted"}
            finally:
                exc.close()
            raise CloudruError(service, exc.code, self.redact(detail)) from None
        except (urllib.error.URLError, OSError, ValueError, UnicodeError):
            raise CloudruError(service, None, {"message": "Transport or JSON decoding failure"}) from None

    def compute_list(self, resource):
        items, pages, offset = [], [], 0
        for _ in range(100):
            page = self.request("compute", "/api/v1/" + resource,
                                {"project_id": self.project_id, "limit": 100, "offset": offset})
            batch, total = page["items"], page["total"]
            pages.append(page)
            items.extend(batch)
            if len(items) == total:
                return {"items": items, "total": total, "pages": pages, "complete": True}
            if not batch or len(items) > total:
                raise ValueError("Incomplete or inconsistent Compute inventory")
            offset += len(batch)
        raise ValueError("Compute pagination exceeded its bound")

    def clusters(self):
        items, pages, token, seen = [], [], "", set()
        for _ in range(100):
            page = self.request("mk8s", "/v3/clusters",
                {"projectId": self.project_id, "pageSize": 100, "pageToken": token})
            pages.append(page)
            items.extend(page["clusters"])
            token = page.get("nextPageToken", "")
            if not token:
                return {"clusters": items, "pages": pages, "complete": True}
            if token in seen:
                raise ValueError("Repeated Kubernetes pagination token")
            seen.add(token)
        raise ValueError("Kubernetes pagination exceeded its bound")


def select_flavor(configuration, *, cpu, ram, purpose, zone):
    candidates = [f for f in configuration["flavors"]
        if f["cpu"] == cpu and f["ram"] == ram and f["gpu"] == 0
        and f["oversubscription"] == "1:1" and f["purpose"] == purpose
        and any(z["zoneName"] == zone and z["flavorZoneState"] == "FLAVOR_ZONE_STATE_AVAILABLE"
                for z in f.get("availabilityZones", []))]
    if len(candidates) != 1:
        raise ValueError("No unique available 100%-CPU flavor for the requested role and zone")
    return candidates[0]


def quote_request(project_id, configuration, node_count, zone="ru.AZ-2"):
    master = select_flavor(configuration, cpu=2, ram=4,
                           purpose="FLAVOR_PURPOSE_CONTROLPLANE", zone=zone)
    worker = select_flavor(configuration, cpu=4, ram=8,
                           purpose="FLAVOR_PURPOSE_DATAPLANE", zone=zone)
    disk = next(d for d in configuration["diskTypes"] if d["name"] == "SSD" and zone in d["zones"])
    # Networking is quoted separately. The legacy calculator silently omits
    # rentPublicIpCount in observed responses, so do not imply it is included.
    return {"projectId": project_id, "master": {"count": 1, "flavorId": master["flavorId"]},
            "nodePools": [{"count": node_count, "flavorId": worker["flavorId"],
                           "disk": {"size": "40", "typeId": disk["diskTypeId"]}}]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--zone", default="ru.AZ-2")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    client = ReadClient(load_profile())
    now = datetime.now(UTC)
    report = {"at": now.isoformat(), "read_only": True, "created_resources": [],
              "project_id": client.project_id, "zone": args.zone,
              "provisioning_ready": False, "errors": {}, "observations": {}}

    def save(name, value):
        (args.output / (name + ".json")).write_text(
            json.dumps(client.redact(value), ensure_ascii=False, indent=2) + "\n")

    def observe(name, fn):
        observed_at = datetime.now(UTC).isoformat()
        try:
            value = fn()
            evidence = {"observed_at": observed_at, "ok": True, "response": value}
        except CloudruError as exc:
            evidence = {"observed_at": observed_at, "ok": False,
                        "http_status": exc.status, "detail": exc.detail}
        except (ValueError, KeyError, TypeError):
            evidence = {"observed_at": observed_at, "ok": False,
                        "detail": "Unexpected or incomplete API response; review schema"}
        save(name, evidence)
        return name, evidence

    queries = {
        "project": lambda: client.request("organization", "/v3/projects/" + client.project_id),
        "quota_types": lambda: client.request("organization", "/v3/quotas/resourceTypes"),
        "quota_usages": lambda: client.request("organization", "/v3/quotas/usages",
            {"subject_type_codes": "QUOTA_SUBJECT_TYPE_PROJECT", "subject_ids": client.project_id,
             "page_size": 1000}),
        "clusters": client.clusters,
        "product_configuration": lambda: client.request("mk8s", "/v3/productConfiguration",
                                                        {"projectId": client.project_id}),
        "mk8s_quotas_legacy": lambda: client.request("mk8s", "/v2/quotas/project/" + client.project_id),
        "compute_usage": lambda: client.request("compute", "/api/v1/project-entity-usage",
                                               {"project_id": client.project_id}),
        "billing_access": lambda: client.request("organization", "/v1/consumption",
            {"project_ids": client.project_id, "start_date": now.strftime("%Y-%m-%dT00:00:00Z"),
             "end_date": now.isoformat(), "page_filter.limit": 100, "page_filter.page": 1}),
    }
    for resource in ("vms", "disks", "subnets", "nat-gateways", "floating-ips"):
        queries[resource] = lambda r=resource: client.compute_list(r)
    observations = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(observe, name, fn) for name, fn in queries.items()]
        for future in as_completed(futures):
            name, evidence = future.result()
            observations[name] = evidence
            report["observations"][name] = {"ok": evidence["ok"], "file": name + ".json"}
            if not evidence["ok"]:
                report["errors"][name] = evidence
    configuration = observations["product_configuration"]
    if configuration["ok"]:
        for count in (1, 4):
            name = f"quote_{count}_nodes"
            def quote(n=count):
                body = quote_request(client.project_id, configuration["response"], n, args.zone)
                save(f"quote_{n}_nodes_request", body)
                return client.request("mk8s", QUOTE_PATH, method="POST", body=body)
            _, evidence = observe(name, quote)
            report["observations"][name] = {"ok": evidence["ok"], "file": name + ".json"}
            if evidence["ok"]:
                report[name + "_rub_per_hour"] = evidence["response"]["totalPrivatePriceWithVatPerHour"]
            else:
                report["errors"][name] = evidence
    report["limitations"] = [
        "Quota access failure, empty quota lists and legacy -1 limits are not proof of sufficient infrastructure quotas.",
        "Billing query verifies access only; it is neither a full consumption export nor a live grant balance.",
        "Price estimates include master, working nodes and their disks; networking/registry/monitoring are separate.",
        "Catalog availability does not reserve capacity or guarantee provisioning success.",
        "Deployment requires reviewed effective quotas, complete budget, Cloud.ru adapter and a tested stop guard.",
    ]
    save("preflight", report)
    print(json.dumps({k: report[k] for k in ("read_only", "created_resources", "provisioning_ready",
                                            "project_id", "observations", "errors")}, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
