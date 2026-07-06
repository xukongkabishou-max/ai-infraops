USE `infraops`;

CREATE TABLE IF NOT EXISTS `machine_hosts` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `hostname` VARCHAR(128) NOT NULL DEFAULT '',
  `public_ip` VARCHAR(64) NOT NULL DEFAULT '',
  `private_ip` VARCHAR(64) NOT NULL DEFAULT '',
  `node_exporter_url` VARCHAR(512) NOT NULL,
  `status` ENUM('active','unreachable') NOT NULL DEFAULT 'unreachable',
  `last_error` TEXT NULL,
  `last_seen_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_machine_hosts_node_exporter_url` (`node_exporter_url`),
  KEY `idx_machine_hosts_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `rbac_permissions` (`code`, `name`, `permission_type`, `description`, `is_active`)
VALUES
  ('host:list', '查看机器资源信息', 'api', '查看主机列表和机器资源指标', 1),
  ('host:create', '添加机器资源主机', 'api', '添加 node-exporter 主机', 1),
  ('host:delete', '删除机器资源主机', 'api', '删除 node-exporter 主机', 1)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `is_active` = 1;

INSERT IGNORE INTO `rbac_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `rbac_roles` r, `rbac_permissions` p
WHERE r.code = 'super_admin' AND p.code IN ('host:list', 'host:create', 'host:delete');

INSERT INTO `rbac_menus` (`title`, `code`, `path`, `icon`, `parent_id`, `permission_id`, `sort_order`, `is_visible`, `is_active`)
VALUES
  ('机器资源信息', 'machine.resources', '/machine-resources', 'server', NULL, (SELECT id FROM `rbac_permissions` WHERE code = 'host:list'), 20, 1, 1)
ON DUPLICATE KEY UPDATE
  `title` = VALUES(`title`),
  `path` = VALUES(`path`),
  `icon` = VALUES(`icon`),
  `permission_id` = VALUES(`permission_id`),
  `sort_order` = VALUES(`sort_order`),
  `is_visible` = VALUES(`is_visible`),
  `is_active` = VALUES(`is_active`);
