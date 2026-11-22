ALTER TABLE social_accounts
  MODIFY status ENUM('connected','expired','error','disconnected','revoked') NOT NULL DEFAULT 'connected';

CREATE TABLE IF NOT EXISTS channel_sync_logs (
  sync_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  social_account_id BIGINT UNSIGNED NOT NULL,
  kind ENUM('metrics','inbox') NOT NULL,
  status ENUM('pending','syncing','success','failed') NOT NULL,
  records_updated INT UNSIGNED NOT NULL DEFAULT 0,
  error_code VARCHAR(100) NULL,
  started_at DATETIME NOT NULL,
  finished_at DATETIME NULL,
  KEY idx_channel_sync (social_account_id,kind,sync_id),
  FOREIGN KEY (social_account_id) REFERENCES social_accounts(social_account_id) ON DELETE CASCADE
) ENGINE=InnoDB;
