USE `infraops`;

CREATE TABLE IF NOT EXISTS `monitoring_platforms` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(128) NOT NULL,
  `platform_type` VARCHAR(32) NOT NULL,
  `base_url` VARCHAR(2048) NOT NULL,
  `description` VARCHAR(512) NOT NULL DEFAULT '',
  `is_enabled` TINYINT(1) NOT NULL DEFAULT 1,
  `sort_order` INT UNSIGNED NOT NULL DEFAULT 0,
  `status` ENUM('configured','active','unreachable') NOT NULL DEFAULT 'configured',
  `last_error` TEXT NULL,
  `last_checked_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_monitoring_platforms_type_url` (`platform_type`, `base_url`(512)),
  KEY `idx_monitoring_platforms_enabled_sort` (`is_enabled`, `sort_order`, `id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `rbac_permissions` (`code`, `name`, `permission_type`, `description`, `is_active`)
VALUES
  ('monitoring:platform:list', '查看监控平台', 'api', '查看已启用的外部监控平台入口', 1),
  ('monitoring:platform:manage', '维护监控平台', 'api', '添加、修改、检测和删除外部监控平台', 1)
ON DUPLICATE KEY UPDATE
  `name` = VALUES(`name`),
  `permission_type` = VALUES(`permission_type`),
  `description` = VALUES(`description`),
  `is_active` = 1;

INSERT IGNORE INTO `rbac_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id
FROM `rbac_roles` r
JOIN `rbac_permissions` p ON p.code IN ('page:monitoring:view', 'monitoring:platform:list')
WHERE r.code IN ('super_admin', 'ops', 'rd');

INSERT IGNORE INTO `rbac_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id
FROM `rbac_roles` r
JOIN `rbac_permissions` p ON p.code = 'monitoring:platform:manage'
WHERE r.code IN ('super_admin', 'ops');
