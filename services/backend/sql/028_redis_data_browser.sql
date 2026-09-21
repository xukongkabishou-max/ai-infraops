USE `infraops`;

CREATE TABLE IF NOT EXISTS redis_instance_configs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  middleware_instance_id BIGINT UNSIGNED NOT NULL,
  deployment_mode ENUM('standalone','cluster') NOT NULL DEFAULT 'standalone',
  database_count SMALLINT UNSIGNED NOT NULL DEFAULT 16,
  username VARCHAR(255) NOT NULL DEFAULT '',
  tls_enabled TINYINT(1) NOT NULL DEFAULT 0,
  verify_tls TINYINT(1) NOT NULL DEFAULT 1,
  connect_timeout_ms INT UNSIGNED NOT NULL DEFAULT 4000,
  read_timeout_ms INT UNSIGNED NOT NULL DEFAULT 6000,
  max_value_bytes INT UNSIGNED NOT NULL DEFAULT 1048576,
  scan_batch_size INT UNSIGNED NOT NULL DEFAULT 200,
  bootstrap_endpoints_json JSON NOT NULL,
  topology_json JSON NULL,
  topology_fingerprint CHAR(64) NULL,
  topology_checked_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_redis_instance_config (middleware_instance_id),
  CONSTRAINT fk_redis_instance_config_instance
    FOREIGN KEY (middleware_instance_id) REFERENCES middleware_instances(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS redis_instance_nodes (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  redis_config_id BIGINT UNSIGNED NOT NULL,
  node_id VARCHAR(128) NULL,
  host VARCHAR(255) NOT NULL,
  port SMALLINT UNSIGNED NOT NULL,
  role VARCHAR(32) NOT NULL DEFAULT 'seed',
  is_seed TINYINT(1) NOT NULL DEFAULT 0,
  status VARCHAR(24) NOT NULL DEFAULT 'unknown',
  last_error VARCHAR(512) NULL,
  last_checked_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_redis_node_endpoint (redis_config_id,host,port),
  KEY idx_redis_node_status (redis_config_id,status),
  CONSTRAINT fk_redis_node_config
    FOREIGN KEY (redis_config_id) REFERENCES redis_instance_configs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS redis_import_batches (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  operation_id CHAR(36) NOT NULL,
  middleware_instance_id BIGINT UNSIGNED NOT NULL,
  instance_fingerprint CHAR(64) NOT NULL,
  database_index SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  key_prefix VARCHAR(255) NOT NULL DEFAULT 'import',
  overwrite TINYINT(1) NOT NULL DEFAULT 0,
  file_count TINYINT UNSIGNED NOT NULL,
  status VARCHAR(24) NOT NULL DEFAULT 'running',
  written_files TINYINT UNSIGNED NOT NULL DEFAULT 0,
  failed_files TINYINT UNSIGNED NOT NULL DEFAULT 0,
  written_keys INT UNSIGNED NOT NULL DEFAULT 0,
  failed_keys INT UNSIGNED NOT NULL DEFAULT 0,
  error_summary VARCHAR(1000) NOT NULL DEFAULT '',
  actor_id BIGINT UNSIGNED NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  finished_at DATETIME(6) NULL,
  UNIQUE KEY uq_redis_import_operation (operation_id),
  KEY idx_redis_import_instance_time (middleware_instance_id,created_at),
  CONSTRAINT fk_redis_import_instance
    FOREIGN KEY (middleware_instance_id) REFERENCES middleware_instances(id) ON DELETE CASCADE,
  CONSTRAINT fk_redis_import_actor
    FOREIGN KEY (actor_id) REFERENCES rbac_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS redis_import_files (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  batch_id BIGINT UNSIGNED NOT NULL,
  original_name VARCHAR(255) NOT NULL,
  stored_path VARCHAR(512) NOT NULL,
  redis_key VARCHAR(512) NOT NULL,
  content_type VARCHAR(128) NOT NULL DEFAULT '',
  size_bytes INT UNSIGNED NOT NULL,
  sha256 CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL DEFAULT 'pending',
  error_message VARCHAR(1000) NOT NULL DEFAULT '',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6) NULL,
  KEY idx_redis_import_file_batch (batch_id),
  CONSTRAINT fk_redis_import_file_batch
    FOREIGN KEY (batch_id) REFERENCES redis_import_batches(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO rbac_permissions (code,name,permission_type,description,is_active)
VALUES
  ('redis:data:read','查询 Redis 数据','api','浏览 Redis key 和查询值',1),
  ('redis:data:write','写入 Redis 数据','api','创建、修改、删除 Redis key 和导入文件',1)
ON DUPLICATE KEY UPDATE name=VALUES(name), is_active=VALUES(is_active);

INSERT IGNORE INTO rbac_role_permissions (role_id,permission_id)
SELECT r.id,p.id
FROM rbac_roles r
JOIN rbac_permissions p ON p.code IN ('redis:data:read','redis:data:write')
WHERE r.code IN ('super_admin','ops');
