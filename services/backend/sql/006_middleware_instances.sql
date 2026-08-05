USE `infraops`;

CREATE TABLE IF NOT EXISTS `middleware_instances` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `environment_id` BIGINT UNSIGNED NOT NULL,
  `middleware_type` VARCHAR(32) NOT NULL,
  `instance_name` VARCHAR(128) NOT NULL,
  `base_url` VARCHAR(512) NOT NULL,
  `username` VARCHAR(255) NOT NULL,
  `password_ciphertext` VARBINARY(4096) NOT NULL,
  `password_nonce` VARBINARY(12) NOT NULL,
  `status` ENUM('configured','active','unreachable','disabled') NOT NULL DEFAULT 'configured',
  `last_error` TEXT NULL,
  `last_seen_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_middleware_instances_type_url` (`middleware_type`, `base_url`),
  KEY `idx_middleware_instances_environment_id` (`environment_id`),
  KEY `idx_middleware_instances_status` (`status`),
  CONSTRAINT `fk_middleware_instances_environment`
    FOREIGN KEY (`environment_id`) REFERENCES `infra_environments` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `rbac_permissions` (`code`, `name`, `permission_type`, `description`, `is_active`)
VALUES
  ('middleware:list', '查看中间件实例', 'api', '查看已登记的中间件实例', 1),
  ('middleware:create', '添加中间件实例', 'api', '登记中间件连接信息', 1),
  ('middleware:delete', '删除中间件实例', 'api', '删除中间件连接信息', 1)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `is_active` = 1;

INSERT IGNORE INTO `rbac_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `rbac_roles` r, `rbac_permissions` p
WHERE r.code = 'super_admin' AND p.code LIKE 'middleware:%';
