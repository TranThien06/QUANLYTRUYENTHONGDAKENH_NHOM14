CREATE TABLE email_verification_codes (
  user_id BIGINT UNSIGNED PRIMARY KEY,
  code_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  expires_at DATETIME NOT NULL,
  sent_at DATETIME NOT NULL,
  failed_attempts INT NOT NULL DEFAULT 0,
  consumed_at DATETIME NULL,
  FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB;
