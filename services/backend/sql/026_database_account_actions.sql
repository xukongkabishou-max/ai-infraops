CREATE TABLE IF NOT EXISTS database_account_action_operations (
  operation_id CHAR(36) NOT NULL PRIMARY KEY,
  middleware_instance_id BIGINT UNSIGNED NOT NULL,
  instance_fingerprint CHAR(64) NOT NULL,
  user_identity VARCHAR(255) NOT NULL,
  identity_fingerprint CHAR(64) NOT NULL,
  request_digest CHAR(64) NOT NULL,
  action VARCHAR(16) NOT NULL,
  status VARCHAR(24) NOT NULL,
  message VARCHAR(255) NOT NULL DEFAULT '',
  lock_key CHAR(64) NULL,
  actor_id BIGINT UNSIGNED NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_database_account_action_lock (lock_key),
  KEY idx_database_account_action_target (instance_fingerprint,user_identity,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
