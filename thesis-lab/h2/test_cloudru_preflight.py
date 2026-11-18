"""Offline checks for read-only scope, complete inventories and zero-node scheduling."""
import copy
import unittest
from unittest.mock import patch

from h2.cloudru_manifests import POOL_LABEL, cloudru_objects
from h2.cloudru_preflight import ReadClient, select_flavor
from h2.manifests import objects


PROFILE = {"project_id": "11111111-1111-4111-8111-111111111111",
           "key_id": "private-key-id", "key_secret": "private-key-secret"}
SYSTEM = "22222222-2222-4222-8222-222222222222"
WORKER = "33333333-3333-4333-8333-333333333333"


class CloudruPreflightTests(unittest.TestCase):
    def setUp(self):
        with patch("h2.cloudru_preflight.authenticate", return_value="private-bearer-token"):
            self.client = ReadClient(PROFILE)

    def test_mutations_rejected_before_network_call(self):
        with patch("h2.cloudru_preflight.urllib.request.build_opener") as opener:
            for method in ("POST", "PATCH", "DELETE", "PUT"):
                with self.assertRaises(ValueError):
                    self.client.request("mk8s", "/v3/clusters", method=method, body={})
            opener.assert_not_called()

    def test_nested_error_redaction(self):
        data = {"details": [{"message": "private-key-id private-key-secret private-bearer-token"}]}
        self.assertEqual(self.client.redact(data),
                         {"details": [{"message": "[REDACTED] [REDACTED] [REDACTED]"}]})

    def test_compute_inventory_reads_all_pages_and_rejects_missing_page(self):
        pages = [{"items": [{"id": "a"}], "total": 2}, {"items": [{"id": "b"}], "total": 2}]
        with patch.object(self.client, "request", side_effect=pages) as request:
            self.assertEqual(self.client.compute_list("vms")["items"], [{"id": "a"}, {"id": "b"}])
            self.assertEqual(request.call_args.args[2]["offset"], 1)
        with patch.object(self.client, "request", return_value={"items": [], "total": 2}):
            with self.assertRaises(ValueError):
                self.client.compute_list("vms")

    def test_repeated_cluster_cursor_fails(self):
        with patch.object(self.client, "request", return_value={"clusters": [], "nextPageToken": "again"}):
            with self.assertRaises(ValueError):
                self.client.clusters()

    def test_sold_out_zone_is_not_selected(self):
        flavor = {"cpu": 4, "ram": 8, "gpu": 0, "oversubscription": "1:1", "purpose": "worker",
                  "availabilityZones": [{"zoneName": "ru.AZ-2", "flavorZoneState": "FLAVOR_ZONE_STATE_SOLD_OUT"}]}
        with self.assertRaises(ValueError):
            select_flavor({"flavors": [flavor]}, cpu=4, ram=8, purpose="worker", zone="ru.AZ-2")

    def test_cloudru_selectors_preserve_workload_and_keda_policy(self):
        baseline = objects("example.invalid/frozen-image@sha256:test")
        rendered = cloudru_objects("example.invalid/frozen-image@sha256:test",
                                   system_pool_id=SYSTEM, worker_pool_id=WORKER)
        normalized = copy.deepcopy(rendered)
        for original, actual in zip(baseline, normalized):
            if original["kind"] == "Deployment":
                name = original["metadata"]["name"]
                pod = actual["spec"]["template"]["spec"]
                if name == "coordinator":
                    self.assertEqual(pod["nodeSelector"], {POOL_LABEL: SYSTEM})
                else:
                    self.assertNotIn("nodeSelector", pod)
                    self.assertEqual(pod["affinity"].pop("nodeAffinity"), {
                        "requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": [
                            {"matchExpressions": [{"key": POOL_LABEL, "operator": "NotIn", "values": [SYSTEM]}]}]}})
                    self.assertEqual(actual["spec"]["template"]["metadata"].pop("annotations"),
                                     {"firefly-h2/expected-pool-id": WORKER})
                self.assertEqual(pod.pop("imagePullSecrets"), [{"name": "cloud-registry-secret"}])
                pod["nodeSelector"] = original["spec"]["template"]["spec"]["nodeSelector"]
        self.assertEqual(normalized, baseline)
        with self.assertRaises(ValueError):
            cloudru_objects("image", system_pool_id=SYSTEM, worker_pool_id=SYSTEM)


if __name__ == "__main__":
    unittest.main()
