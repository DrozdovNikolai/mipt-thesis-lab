"""Lifecycle boundaries that matter before paid resources are created."""
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from h2.cloudru_ops import Cloud, WriteClient, assert_owned, node_pool_request, private_write
from h2.cloudru_manifests import cloudru_objects
from h2.cloudru_preflight import CloudruError
from h2.test_cloudru_preflight import PROFILE, SYSTEM, WORKER


class LifecycleTests(unittest.TestCase):
    def test_compact_worker_still_has_one_pod_per_node_and_frozen_image(self):
        image = "registry.invalid/asr@sha256:frozen"
        rows = cloudru_objects(image, system_pool_id=SYSTEM, worker_pool_id=WORKER, compact=True)
        worker = next(o for o in rows if o["kind"] == "Deployment" and o["metadata"]["name"] == "worker")
        pod = worker["spec"]["template"]["spec"]
        self.assertEqual(pod["containers"][0]["image"], image)
        self.assertEqual(pod["containers"][0]["resources"],
                         {"requests": {"cpu": "1500m", "memory": "2Gi"}, "limits": {"cpu": "1500m", "memory": "2Gi"}})
        self.assertTrue(pod["affinity"]["podAntiAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"])

    def test_pool_cannot_exceed_quota_by_size_or_surge(self):
        p = node_pool_request("cluster", "subnet", "flavor", "pool")
        self.assertEqual(p["scalePolicy"]["autoScale"], {"minCount": 0, "maxCount": 3, "initialCount": 0})
        self.assertEqual(p["updateConfiguration"]["rollingUpdatePolicy"]["maxSurge"], 0)
        for n in (-1, 4, True, 1.5):
            with self.assertRaises(ValueError):
                node_pool_request("c", "s", "f", "p", fixed=n)

    def test_existing_worker_pool_prevents_overlapping_trial(self):
        c = Cloud.__new__(Cloud)
        c.state = {"deadline": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                   "groups": {"previous": {"id": "some-id"}}}
        with patch.object(c, "mutate") as mutation:
            with self.assertRaises(ValueError):
                c.create_group("next-trial")
            mutation.assert_not_called()

    def test_deadline_checked_before_creation(self):
        c = Cloud.__new__(Cloud)
        c.state = {"deadline": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}
        with patch.object(c, "mutate") as mutation:
            with self.assertRaises(RuntimeError):
                c.create_group("new-trial")
            mutation.assert_not_called()

    def test_deletion_identity_requires_id_name_and_project(self):
        saved = {"id": "owned-id", "name": "owned-name"}
        for obj in ({"id": "other", "name": "owned-name", "projectId": "project"},
                    {"id": "owned-id", "name": "other", "projectId": "project"},
                    {**saved, "projectId": "other"}):
            with self.assertRaises(ValueError):
                assert_owned(obj, saved, "project")

    def test_private_output_has_no_group_access_and_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "key"
            private_write(path, "secret")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            link = Path(d) / "link"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                private_write(link, "overwrite")
            self.assertEqual(path.read_text(), "secret")

    def test_iam_filter_encodes_spaces_for_actual_api(self):
        with patch("h2.cloudru_preflight.authenticate", return_value="token"):
            c = WriteClient(PROFILE)
        with patch("h2.cloudru_ops.urllib.request.build_opener") as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{}'
            c.request("iam", "/api/v3/permissions", {"filter": "resource_id=p AND subject_id=s"})
            request = opener.return_value.open.call_args.args[0]
            self.assertIn("%20AND%20", request.full_url)
            self.assertNotIn("+", request.full_url)

    def test_transport_failure_retries_reads_but_never_repeats_a_create(self):
        with patch("h2.cloudru_preflight.authenticate", return_value="token"):
            c = WriteClient(PROFILE)
        error = CloudruError("mk8s", None, {"message": "lost response"})
        with patch.object(c, "_request_once", side_effect=[error, {"clusters": []}]) as request, patch("h2.cloudru_ops.time.sleep"):
            self.assertEqual(c.request("mk8s", "/v3/clusters"), {"clusters": []})
            self.assertEqual(request.call_count, 2)
        with patch.object(c, "_request_once", side_effect=error) as request:
            with self.assertRaises(CloudruError):
                c.request("mk8s", "/v3/clusters", method="POST", body={})
            self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
