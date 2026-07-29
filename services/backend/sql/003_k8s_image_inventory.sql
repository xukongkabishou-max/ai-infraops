CREATE TABLE IF NOT EXISTS `infra_environments` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `code` VARCHAR(64) NOT NULL,
  `name` VARCHAR(128) NOT NULL,
  `description` TEXT NULL,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_infra_environments_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET @environment_column_sql = IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'machine_hosts' AND COLUMN_NAME = 'environment_id') = 0,
  'ALTER TABLE `machine_hosts` ADD COLUMN `environment_id` BIGINT UNSIGNED NULL AFTER `id`',
  'SELECT 1'
);
PREPARE environment_column_statement FROM @environment_column_sql;
EXECUTE environment_column_statement;
DEALLOCATE PREPARE environment_column_statement;

SET @environment_index_sql = IF(
  (SELECT COUNT(*) FROM information_schema.STATISTICS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'machine_hosts' AND INDEX_NAME = 'idx_machine_hosts_environment_id') = 0,
  'ALTER TABLE `machine_hosts` ADD KEY `idx_machine_hosts_environment_id` (`environment_id`)',
  'SELECT 1'
);
PREPARE environment_index_statement FROM @environment_index_sql;
EXECUTE environment_index_statement;
DEALLOCATE PREPARE environment_index_statement;

SET @environment_fk_sql = IF(
  (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
   WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'machine_hosts' AND CONSTRAINT_NAME = 'fk_machine_hosts_environment') = 0,
  'ALTER TABLE `machine_hosts` ADD CONSTRAINT `fk_machine_hosts_environment` FOREIGN KEY (`environment_id`) REFERENCES `infra_environments` (`id`) ON DELETE SET NULL',
  'SELECT 1'
);
PREPARE environment_fk_statement FROM @environment_fk_sql;
EXECUTE environment_fk_statement;
DEALLOCATE PREPARE environment_fk_statement;

CREATE TABLE IF NOT EXISTS `k8s_clusters` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `host_id` BIGINT UNSIGNED NULL,
  `environment_id` BIGINT UNSIGNED NOT NULL,
  `name` VARCHAR(128) NOT NULL,
  `api_server_url` VARCHAR(512) NOT NULL DEFAULT '',
  `credential_ref` VARCHAR(255) NOT NULL DEFAULT '',
  `credential_name` VARCHAR(255) NOT NULL DEFAULT '',
  `credential_ciphertext` MEDIUMBLOB NULL,
  `credential_nonce` VARBINARY(12) NULL,
  `credential_fingerprint` CHAR(64) NOT NULL DEFAULT '',
  `context_name` VARCHAR(128) NOT NULL DEFAULT '',
  `verify_ssl` TINYINT(1) NOT NULL DEFAULT 1,
  `status` ENUM('configured','active','unreachable','disabled') NOT NULL DEFAULT 'configured',
  `last_error` TEXT NULL,
  `last_seen_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_k8s_clusters_host_id` (`host_id`),
  UNIQUE KEY `uk_k8s_clusters_environment_name` (`environment_id`, `name`),
  KEY `idx_k8s_clusters_status` (`status`),
  CONSTRAINT `fk_k8s_clusters_host` FOREIGN KEY (`host_id`) REFERENCES `machine_hosts` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_k8s_clusters_environment` FOREIGN KEY (`environment_id`) REFERENCES `infra_environments` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `rbac_permissions` (`code`, `name`, `permission_type`, `description`, `is_active`)
VALUES
  ('environment:list', '查看环境', 'api', '查看环境及其主机、K8S 集群数量', 1),
  ('k8s:cluster:list', '查看 K8S 集群', 'api', '查看环境下的 K8S 集群', 1),
  ('k8s:cluster:create', '登记 K8S 集群', 'api', '登记 K8S API 与 kubeconfig 引用', 1),
  ('k8s:cluster:delete', '删除 K8S 集群', 'api', '删除 K8S 集群登记信息', 1),
  ('k8s:image:list', '查看 K8S 镜像', 'api', '查看 namespace 下工作负载使用的镜像', 1)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `is_active` = 1;

INSERT IGNORE INTO `rbac_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id
FROM `rbac_roles` r
JOIN `rbac_permissions` p
WHERE r.code = 'super_admin'
  AND p.code IN (
    'environment:list',
    'k8s:cluster:list',
    'k8s:cluster:create',
    'k8s:cluster:delete',
    'k8s:image:list'
  );
