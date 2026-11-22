import logging
from datetime import timedelta
from app.common import now
from app.config import settings
from app.db import transaction, json_value
from app.events import notify_managers
from app.modules.channels import TOKEN_STATUS, credentials
from app.security import encrypt
from app.social import refresh_remote, account_metrics, post_metrics, inbox_remote, ProviderError


def refresh_tokens():
    with transaction() as db:
        candidates = db.all(
            """SELECT a.social_account_id FROM social_accounts a JOIN social_account_tokens t ON t.social_account_id=a.social_account_id
            JOIN platforms p ON p.platform_id=a.platform_id
            WHERE (%s='mock' OR p.code='tiktok' OR t.expires_at<=UTC_TIMESTAMP())
            AND (a.status='connected' OR (a.status='expired' AND a.status_message IN ('TOKEN_REFRESH_PENDING','TOKEN_EXPIRED')))
            AND t.expires_at<=DATE_ADD(UTC_TIMESTAMP(),INTERVAL 30 MINUTE)
            AND (t.last_refreshed_at IS NULL OR t.last_refreshed_at<DATE_SUB(UTC_TIMESTAMP(),INTERVAL 10 MINUTE) OR (a.status='connected' AND t.expires_at<=UTC_TIMESTAMP()))
            ORDER BY t.last_refreshed_at,t.expires_at LIMIT 20""",
            (settings.social_mode,),
        )
    for candidate in candidates:
        account_id = candidate["social_account_id"]
        try:
            refresh_account_token(account_id)
        except Exception as error:
            logging.error("task=token_refresh account_id=%s code=%s", account_id, type(error).__name__)


def refresh_account_token(account_id):
    with transaction() as db:
        account = db.one(
            "SELECT a.*,p.code FROM social_accounts a JOIN platforms p ON p.platform_id=a.platform_id WHERE a.social_account_id=%s FOR UPDATE",
            (account_id,),
        )
        if not account or not (
            account["status"] == "connected"
            or (
                account["status"] == "expired"
                and account["status_message"] in ("TOKEN_REFRESH_PENDING", "TOKEN_EXPIRED")
            )
        ):
            return
        current = db.one(
            "SELECT * FROM social_account_tokens WHERE social_account_id=%s FOR UPDATE",
            (account["social_account_id"],),
        )
        if (
            not current
            or not current["expires_at"]
            or current["expires_at"] > now() + timedelta(minutes=30)
            or (
                current["last_refreshed_at"]
                and (account["status"] == "expired" or current["expires_at"] > now())
                and current["last_refreshed_at"] > now() - timedelta(minutes=10)
            )
        ):
            return
        if settings.social_mode == "live" and account["code"] != "tiktok" and current["expires_at"] > now():
            return
        db.execute(
            "UPDATE social_account_tokens SET last_refreshed_at=UTC_TIMESTAMP() WHERE social_account_id=%s",
            (account["social_account_id"],),
        )
        try:
            auth = credentials(db, account["social_account_id"])
            started_at = now()
            fresh = refresh_remote(account, auth)
            db.execute(
                "UPDATE social_account_tokens SET access_token_enc=%s,refresh_token_enc=%s,expires_at=%s,refresh_fail_count=0 WHERE social_account_id=%s",
                (
                    encrypt(fresh["access_token"]),
                    encrypt(fresh["refresh_token"]),
                    started_at + timedelta(seconds=fresh["expires_in"]),
                    account["social_account_id"],
                ),
            )
        except ProviderError as error:
            logging.warning("task=token_refresh account_id=%s code=%s", account_id, error.code)
            db.execute(
                "UPDATE social_account_tokens SET refresh_fail_count=refresh_fail_count+1 WHERE social_account_id=%s",
                (account["social_account_id"],),
            )
            if error.code == "RECONNECT_REQUIRED":
                db.execute(
                    "UPDATE social_accounts SET status='expired',status_message='RECONNECT_REQUIRED' WHERE social_account_id=%s",
                    (account["social_account_id"],),
                )
                notify_managers(
                    db,
                    account["workspace_id"],
                    "token_expired",
                    "Cần kết nối lại kênh",
                    "social_account",
                    account["social_account_id"],
                )

            elif account["status"] == "connected" and current["expires_at"] <= now():
                db.execute(
                    "UPDATE social_accounts SET status='expired',status_message='TOKEN_REFRESH_PENDING' WHERE social_account_id=%s",
                    (account_id,),
                )
            return

        if account["status"] == "expired":
            db.execute(
                "UPDATE social_accounts SET status='connected',status_message=NULL WHERE social_account_id=%s",
                (account_id,),
            )


def sync_account(db, account):
    auth = credentials(db, account["social_account_id"])
    metrics = account_metrics(account, auth["access_token"])
    yesterday = db.one(
        "SELECT followers_count FROM account_daily_metrics WHERE social_account_id=%s AND metric_date=DATE_SUB(UTC_DATE(),INTERVAL 1 DAY)",
        (account["social_account_id"],),
    )
    gain = (
        metrics["followers_count"] - yesterday["followers_count"]
        if metrics.get("followers_count") is not None
        and yesterday
        and yesterday["followers_count"] is not None
        else None
    )
    db.execute(
        """INSERT INTO account_daily_metrics(social_account_id,metric_date,followers_count,followers_gain,impressions,reach,engagements,extra_metrics)
        VALUES (%s,UTC_DATE(),%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE followers_count=VALUES(followers_count),followers_gain=VALUES(followers_gain),
        impressions=VALUES(impressions),reach=VALUES(reach),engagements=VALUES(engagements),extra_metrics=VALUES(extra_metrics),synced_at=UTC_TIMESTAMP()""",
        (
            account["social_account_id"],
            metrics.get("followers_count"),
            gain,
            metrics.get("impressions"),
            metrics.get("reach"),
            metrics.get("engagements"),
            json_value(metrics.get("extra_metrics", {})),
        ),
    )
    return 1


def sync_inbox(db, account):
    auth = credentials(db, account["social_account_id"])
    variants = db.all(
        "SELECT variant_id,external_post_id FROM post_variants WHERE social_account_id=%s AND status='published' ORDER BY published_at DESC LIMIT 100",
        (account["social_account_id"],),
    )
    threads = inbox_remote(account, auth["access_token"], variants)
    for thread in threads:
        variant_id = None
        if thread.get("external_post_id"):
            row = db.one(
                "SELECT variant_id FROM post_variants WHERE social_account_id=%s AND external_post_id=%s",
                (account["social_account_id"], thread["external_post_id"]),
            )
            variant_id = row["variant_id"] if row else None
        db.execute(
            """INSERT INTO conversations(workspace_id,social_account_id,variant_id,conversation_type,external_id,participant_name,participant_external_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE participant_name=VALUES(participant_name),participant_external_id=VALUES(participant_external_id)""",
            (
                account["workspace_id"],
                account["social_account_id"],
                variant_id,
                thread["conversation_type"],
                thread["external_id"],
                thread.get("participant_name"),
                thread.get("participant_external_id"),
            ),
        )
        conversation = db.one(
            "SELECT conversation_id FROM conversations WHERE social_account_id=%s AND external_id=%s",
            (account["social_account_id"], thread["external_id"]),
        )
        for message in thread["messages"]:
            db.execute(
                """INSERT INTO messages(conversation_id,external_message_id,direction,sender_name,content,sent_at) VALUES (%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE external_message_id=VALUES(external_message_id)""",
                (
                    conversation["conversation_id"],
                    message["external_message_id"],
                    message.get("direction", "inbound"),
                    message.get("sender_name"),
                    message.get("content"),
                    message["sent_at"],
                ),
            )
        db.execute(
            "UPDATE conversations SET last_message_at=(SELECT MAX(sent_at) FROM messages WHERE conversation_id=%s) WHERE conversation_id=%s",
            (conversation["conversation_id"], conversation["conversation_id"]),
        )
    return len(threads)


def sync_accounts():
    for kind, column, interval in (
        ("metrics", "last_metrics_sync_at", "1 DAY"),
        ("inbox", "last_inbox_sync_at", "5 MINUTE"),
    ):
        platform_filter = (
            " AND a.platform_id IN (SELECT platform_id FROM platforms WHERE code='facebook')"
            if kind == "inbox" and settings.social_mode == "live"
            else ""
        )
        with transaction() as db:
            db.execute(
                """UPDATE channel_sync_logs l JOIN social_accounts a ON a.social_account_id=l.social_account_id
                LEFT JOIN social_account_tokens t ON t.social_account_id=a.social_account_id
                SET l.status='failed',l.error_code='CHANNEL_UNAVAILABLE',l.finished_at=UTC_TIMESTAMP()
                WHERE l.kind=%s AND l.status IN ('pending','syncing')
                AND (a.status<>'connected' OR t.social_account_id IS NULL OR t.expires_at<=UTC_TIMESTAMP())""",
                (kind,),
            )
            candidates = db.all(
                f"SELECT a.social_account_id FROM social_accounts a JOIN social_account_tokens t ON t.social_account_id=a.social_account_id WHERE a.status='connected' AND (t.expires_at IS NULL OR t.expires_at>UTC_TIMESTAMP()) AND (a.{column} IS NULL OR a.{column}<DATE_SUB(UTC_TIMESTAMP(),INTERVAL {interval})){platform_filter} ORDER BY a.social_account_id LIMIT 20"
            )
        for candidate in candidates:
            account_id = candidate["social_account_id"]
            sync_id = None
            try:
                with transaction() as db:
                    account = db.one(
                        f"SELECT a.*,p.code FROM social_accounts a JOIN platforms p ON p.platform_id=a.platform_id WHERE a.social_account_id=%s AND a.status='connected' AND (a.{column} IS NULL OR a.{column}<DATE_SUB(UTC_TIMESTAMP(),INTERVAL {interval})) FOR UPDATE",
                        (account_id,),
                    )
                    if not account:
                        continue
                    active = db.one(
                        """SELECT sync_id,status,started_at FROM channel_sync_logs WHERE social_account_id=%s
                        AND kind=%s AND status IN ('pending','syncing') ORDER BY sync_id DESC LIMIT 1 FOR UPDATE""",
                        (account_id, kind),
                    )
                    if active and active["status"] == "syncing":
                        if active["started_at"] > now() - timedelta(minutes=10):
                            continue
                        db.execute(
                            "UPDATE channel_sync_logs SET status='failed',error_code='SYNC_INTERRUPTED',finished_at=UTC_TIMESTAMP() WHERE sync_id=%s",
                            (active["sync_id"],),
                        )
                        active = None
                    if active:
                        sync_id = active["sync_id"]
                        db.execute(
                            "UPDATE channel_sync_logs SET status='syncing',started_at=UTC_TIMESTAMP() WHERE sync_id=%s",
                            (sync_id,),
                        )
                    else:
                        sync_id = db.insert(
                            "channel_sync_logs",
                            {
                                "social_account_id": account_id,
                                "kind": kind,
                                "status": "syncing",
                                "started_at": now(),
                            },
                        )
                with transaction() as db:
                    account = db.one(
                        """SELECT a.*,p.code,t.expires_at FROM social_accounts a JOIN platforms p ON p.platform_id=a.platform_id
                        LEFT JOIN social_account_tokens t ON t.social_account_id=a.social_account_id
                        WHERE a.social_account_id=%s FOR UPDATE""",
                        (account_id,),
                    )
                    active = db.one(
                        "SELECT status FROM channel_sync_logs WHERE sync_id=%s FOR UPDATE", (sync_id,)
                    )
                    if not active or active["status"] != "syncing":
                        continue
                    db.execute(
                        f"UPDATE social_accounts SET {column}=UTC_TIMESTAMP() WHERE social_account_id=%s",
                        (account_id,),
                    )
                    status, error_code, count = "success", None, 0
                    try:
                        if account["status"] != "connected":
                            raise ProviderError("CHANNEL_UNAVAILABLE")
                        if account["expires_at"] and account["expires_at"] <= now():
                            raise ProviderError("TOKEN_EXPIRED")
                        demo = account["external_account_id"] == f"mock-{account['code']}"
                        if demo != (settings.social_mode == "mock"):
                            raise ProviderError("CHANNEL_MODE_MISMATCH")
                        count = (sync_account if kind == "metrics" else sync_inbox)(db, account)
                    except ProviderError as error:
                        status, error_code = "failed", error.code
                        db.execute(
                            "UPDATE social_accounts SET status_message=%s WHERE social_account_id=%s",
                            (error.code, account["social_account_id"]),
                        )
                        if error.code in TOKEN_STATUS:
                            db.execute(
                                "UPDATE social_accounts SET status=%s WHERE social_account_id=%s",
                                (TOKEN_STATUS[error.code], account["social_account_id"]),
                            )
                            notify_managers(
                                db,
                                account["workspace_id"],
                                "token_expired",
                                "Cần kết nối lại kênh",
                                "social_account",
                                account["social_account_id"],
                            )
                    db.execute(
                        """UPDATE channel_sync_logs SET status=%s,records_updated=%s,error_code=%s,
                        finished_at=UTC_TIMESTAMP() WHERE sync_id=%s""",
                        (status, count, error_code, sync_id),
                    )
            except Exception as error:
                logging.error("task=sync_%s code=%s", kind, type(error).__name__)
                if sync_id is not None:
                    with transaction() as db:
                        db.execute(
                            """UPDATE channel_sync_logs SET status='failed',error_code='SYNC_FAILED',
                            finished_at=UTC_TIMESTAMP() WHERE sync_id=%s AND status='syncing'""",
                            (sync_id,),
                        )


def sync_post_snapshots():
    for hours in (1, 24, 168):
        with transaction() as db:
            candidates = db.all(
                "SELECT v.variant_id,v.social_account_id FROM post_variants v WHERE v.status='published' AND v.published_at<=DATE_SUB(UTC_TIMESTAMP(),INTERVAL %s HOUR) AND NOT EXISTS (SELECT 1 FROM metric_sync_points s WHERE s.variant_id=v.variant_id AND s.checkpoint_hours=%s) LIMIT 20",
                (hours, hours),
            )
        for candidate in candidates:
            try:
                with transaction() as db:
                    account = db.one(
                        "SELECT a.*,(SELECT p.code FROM platforms p WHERE p.platform_id=a.platform_id) AS code "
                        "FROM social_accounts a WHERE a.social_account_id=%s FOR UPDATE",
                        (candidate["social_account_id"],),
                    )
                    if not account or account["status"] != "connected":
                        continue
                    variant = db.one(
                        "SELECT * FROM post_variants WHERE variant_id=%s FOR UPDATE",
                        (candidate["variant_id"],),
                    )
                    if (
                        not variant
                        or variant["status"] != "published"
                        or variant["social_account_id"] != account["social_account_id"]
                    ):
                        continue
                    if db.one(
                        "SELECT 1 FROM metric_sync_points WHERE variant_id=%s AND checkpoint_hours=%s",
                        (variant["variant_id"], hours),
                    ):
                        continue
                    metrics = post_metrics(
                        account, variant, credentials(db, account["social_account_id"])["access_token"]
                    )
                    db.execute(
                        "INSERT INTO post_metric_snapshots(variant_id,collected_at,views,likes,comments,shares,extra_metrics) VALUES (%s,UTC_TIMESTAMP(),%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE views=VALUES(views),likes=VALUES(likes),comments=VALUES(comments),shares=VALUES(shares),extra_metrics=VALUES(extra_metrics)",
                        (
                            variant["variant_id"],
                            metrics.get("views"),
                            metrics.get("likes"),
                            metrics.get("comments"),
                            metrics.get("shares"),
                            json_value(metrics.get("extra_metrics", {})),
                        ),
                    )
                    db.insert(
                        "metric_sync_points", {"variant_id": variant["variant_id"], "checkpoint_hours": hours}
                    )
            except Exception as error:
                logging.error("task=post_metrics code=%s", type(error).__name__)
