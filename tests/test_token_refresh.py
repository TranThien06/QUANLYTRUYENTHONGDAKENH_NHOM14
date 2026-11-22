from contextlib import nullcontext
from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import Mock, patch

import httpx

from app import social
from app.jobs import sync


class TokenRefreshTest(TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 1)
        self.account = {
            "social_account_id": 3,
            "workspace_id": 5,
            "external_account_id": "open-id",
            "code": "tiktok",
            "status": "connected",
            "status_message": None,
        }
        self.token = {"expires_at": self.now + timedelta(minutes=15), "last_refreshed_at": None}
        self.db = Mock()
        self.db.one.side_effect = [self.account, self.token]
        self.enterContext(patch.object(sync, "transaction", return_value=nullcontext(self.db)))
        self.enterContext(patch.object(sync, "now", return_value=self.now))
        self.enterContext(patch.object(sync.settings, "social_mode", "live"))
        self.enterContext(patch.object(sync, "credentials", return_value={"refresh_token": "old"}))
        self.notify = self.enterContext(patch.object(sync, "notify_managers"))

    def test_rotated_tokens_are_encrypted_before_channel_recovers(self):
        self.account.update(status="expired", status_message="TOKEN_REFRESH_PENDING")
        self.token["expires_at"] = self.now
        with (
            patch.object(sync, "encrypt", side_effect=[b"encrypted-access", b"encrypted-refresh"]),
            patch.object(
                sync,
                "refresh_remote",
                return_value={"access_token": "access", "refresh_token": "rotated", "expires_in": 7200},
            ),
        ):
            sync.refresh_account_token(3)
        _, saved, recovered = self.db.execute.call_args_list
        self.assertEqual(
            saved.args[1], (b"encrypted-access", b"encrypted-refresh", self.now + timedelta(hours=2), 3)
        )
        self.assertIn("status='connected'", recovered.args[0])

    def test_failed_refresh_records_attempt_without_saving_tokens(self):
        for minutes in (15, 0):
            with self.subTest(minutes_left=minutes):
                self.token["expires_at"] = self.now + timedelta(minutes=minutes)
                self.db.one.side_effect = [self.account, self.token]
                self.db.execute.reset_mock()
                with (
                    patch.object(
                        sync, "refresh_remote", side_effect=social.ProviderError("PROVIDER_NETWORK")
                    ),
                    self.assertLogs(level="WARNING") as logs,
                ):
                    sync.refresh_account_token(3)
                statements = " ".join(call.args[0] for call in self.db.execute.call_args_list)
                self.assertIn("refresh_fail_count=refresh_fail_count+1", statements)
                self.assertNotIn("access_token_enc", statements)
                self.assertEqual("TOKEN_REFRESH_PENDING" in statements, minutes == 0)
                self.assertIn("code=PROVIDER_NETWORK", logs.output[0])

    def test_invalid_grant_requires_reconnection(self):
        response = httpx.Response(400, json={"error": "invalid_grant"})
        with patch.object(social.httpx, "request", return_value=response), self.assertLogs(level="WARNING"):
            sync.refresh_account_token(3)
        self.assertIn("status_message='RECONNECT_REQUIRED'", self.db.execute.call_args.args[0])
        self.notify.assert_called_once()

    def test_refresh_rejects_missing_rotated_token(self):
        result = {"access_token": "access", "open_id": "open-id", "expires_in": 7200}
        with (
            patch.object(social, "call", return_value=result),
            self.assertRaises(social.ProviderError) as error,
        ):
            social.refresh_remote(self.account, {"refresh_token": "old"})
        self.assertEqual(error.exception.code, "INVALID_REFRESH_RESPONSE")
