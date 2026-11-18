"""Offline checks for credential handling; no cloud calls or real secrets."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

from h2 import cloudru_access as access


PROFILE = {"project_id": "11111111-1111-4111-8111-111111111111",
           "key_id": "test-key-id", "key_secret": "test-secret-never-log"}


class CloudruAccessTests(unittest.TestCase):
    def test_profile_is_private_and_cannot_replace_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private/credentials.json"
            access.save_profile(PROFILE, path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(access.load_profile(path), PROFILE)
            with self.assertRaises(FileExistsError):
                access.save_profile({**PROFILE, "key_secret": "different-secret"}, path)
            self.assertEqual(access.load_profile(path), PROFILE)
            path.chmod(0o644)
            with self.assertRaises(access.AccessError):
                access.load_profile(path)

    def test_symlink_is_neither_overwritten_nor_read(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.json"
            access.save_profile(PROFILE, target)
            link = Path(directory) / "link.json"
            link.symlink_to(target)
            with self.assertRaises(OSError):
                access.save_profile(PROFILE, link)
            with self.assertRaises(OSError):
                access.load_profile(link)
            self.assertEqual(access.load_profile(target), PROFILE)

    @patch.object(access.urllib.request, "build_opener")
    def test_authentication_keeps_token_in_memory(self, build_opener):
        response = io.BytesIO(b'{"access_token":"test-bearer-token"}')
        build_opener.return_value.open.return_value = response
        self.assertEqual(access.authenticate(PROFILE), "test-bearer-token")
        request = build_opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, access.TOKEN_URL)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), {"keyId": PROFILE["key_id"],
                                                  "secret": PROFILE["key_secret"]})

    @patch.object(access.urllib.request, "build_opener")
    def test_error_response_cannot_leak_credentials(self, build_opener):
        error = urllib.error.HTTPError(access.TOKEN_URL, 401, PROFILE["key_secret"], {},
                                      io.BytesIO(json.dumps(PROFILE).encode()))
        build_opener.return_value.open.side_effect = error
        with self.assertRaises(access.AccessError) as caught:
            access.authenticate(PROFILE)
        self.assertIn("401", str(caught.exception))
        self.assertNotIn(PROFILE["key_secret"], str(caught.exception))
        self.assertNotIn(PROFILE["key_id"], str(caught.exception))

    @patch.object(access.urllib.request, "build_opener")
    def test_malformed_response_does_not_report_success(self, build_opener):
        for payload in (b'not-json', b'[]', b'{"access_token":""}', b'{"error":"failure"}'):
            with self.subTest(payload=payload):
                build_opener.return_value.open.return_value = io.BytesIO(payload)
                with self.assertRaises(access.AccessError):
                    access.authenticate(PROFILE)

    def test_redirects_are_refused(self):
        handler = access.NoRedirect()
        self.assertIsNone(handler.redirect_request(Mock(), Mock(), 307, "redirect", {},
                                                  "https://example.com/"))


if __name__ == "__main__":
    unittest.main()
