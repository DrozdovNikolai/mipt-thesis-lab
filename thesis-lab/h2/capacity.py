"""Read namespace-scoped pod ages without resetting an in-progress cold start."""
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import ssl
import threading
import time
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def pending_estimates(pods, *, now, cold_start_seconds, excluded_ids):
    if not math.isfinite(cold_start_seconds) or cold_start_seconds < 0:
        raise ValueError("Invalid cold start estimate")
    values = []
    for pod in pods:
        if pod["uid"] in excluded_ids or pod["deleting"] or pod["phase"] not in {"Pending", "Running"}:
            continue
        elapsed = max(0, now - pod["created_at"])
        # Overdue startup is still not a ready worker. Keep a positive margin
        # instead of silently considering a stuck pod available immediately.
        floor = min(30.0, cold_start_seconds)
        values.append(max(floor, cold_start_seconds - elapsed))
    return sorted(values)


class Capacity:
    def __init__(self, *, enabled=None, namespace=None, clock=time.time):
        self.enabled = (os.environ.get("H2_KUBERNETES_CAPACITY") == "1") if enabled is None else enabled
        self.namespace = namespace or os.environ.get("POD_NAMESPACE", "")
        self.clock = clock
        self.lock = threading.Lock()
        self.last_attempt = float("-inf")
        self.last_success = None
        self.pods = []
        self.error = None

    def fetch(self):
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", self.namespace):
            raise ValueError("Invalid experiment namespace")
        root = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        token = (root / "token").read_text().strip()
        context = ssl.create_default_context(cafile=str(root / "ca.crt"))
        url = "https://kubernetes.default.svc/api/v1/namespaces/" + self.namespace + "/pods?labelSelector=app%3Dworker"
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
        with opener.open(req, timeout=1.5) as response:
            body = response.read(1_000_001)
        if len(body) > 1_000_000:
            raise ValueError("Pod inventory exceeds the bounded experiment size")
        result = json.loads(body)
        if result.get("kind") != "PodList" or not isinstance(result.get("items"), list):
            raise ValueError("Incomplete pod inventory")
        rows = []
        for pod in result["items"]:
            meta = pod["metadata"]
            if meta["namespace"] != self.namespace or meta.get("labels", {}).get("app") != "worker":
                raise ValueError("Unexpected pod ownership")
            rows.append({"uid": meta["uid"], "created_at": datetime.fromisoformat(meta["creationTimestamp"].replace("Z", "+00:00")).timestamp(),
                "phase": pod.get("status", {}).get("phase", "Pending"), "deleting": bool(meta.get("deletionTimestamp"))})
        return rows

    def snapshot(self):
        if not self.enabled:
            return {"enabled": False, "fresh": False, "pods": [], "error": None, "age_seconds": None}
        with self.lock:
            now = self.clock()
            if now - self.last_attempt >= 5:
                self.last_attempt = now
                try:
                    self.pods = self.fetch()
                    self.last_success = self.clock()
                    self.error = None
                except Exception as error:
                    # Never include service-account credentials or HTTP bodies.
                    self.error = type(error).__name__ + (" HTTP " + str(error.code) if hasattr(error, "code") else "")
            age = None if self.last_success is None else max(0, self.clock() - self.last_success)
            fresh = age is not None and age <= 15
            return {"enabled": True, "fresh": fresh, "pods": list(self.pods) if fresh else [],
                    "error": self.error, "age_seconds": age}
