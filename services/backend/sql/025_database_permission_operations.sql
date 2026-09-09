CREATE TABLE IF NOT EXISTS database_permission_operations (
  operation_id CHAR(36) NOT NULL PRIMARY KEY,
  middleware_instance_id BIGINT UNSIGNED NOT NULL,
  instance_fingerprint CHAR(64) NOT NULL,
  user_identity VARCHAR(255) NOT NULL,
  request_digest CHAR(64) NOT NULL,
  lock_key CHAR(64) NULL,
  before_plan JSON NOT NULL,
  after_plan JSON NOT NULL,
  account_marker JSON NULL,
  status VARCHAR(24) NOT NULL,
  message VARCHAR(255) NOT NULL DEFAULT '',
  actor_id BIGINT UNSIGNED NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_database_permission_lock (lock_key),
  KEY idx_database_permission_target (instance_fingerprint,user_identity,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
