CREATE DATABASE IF NOT EXISTS `infraops`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `infraops`;

CREATE TABLE IF NOT EXISTS `rbac_users` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `username` VARCHAR(64) NOT NULL,
  `password_hash` VARCHAR(255) NOT NULL,
  `display_name` VARCHAR(128) NOT NULL DEFAULT '',
  `email` VARCHAR(255) NOT NULL DEFAULT '',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `is_superuser` TINYINT(1) NOT NULL DEFAULT 0,
  `last_login_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_rbac_users_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `rbac_roles` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `code` VARCHAR(128) NOT NULL,
  `name` VARCHAR(128) NOT NULL,
  `description` TEXT NULL,
  `is_system` TINYINT(1) NOT NULL DEFAULT 0,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_rbac_roles_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `rbac_permissions` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `code` VARCHAR(128) NOT NULL,
  `name` VARCHAR(128) NOT NULL,
  `permission_type` ENUM('api','page','button','data') NOT NULL DEFAULT 'api',
  `description` TEXT NULL,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_rbac_permissions_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `rbac_user_roles` (
  `user_id` BIGINT UNSIGNED NOT NULL,
  `role_id` BIGINT UNSIGNED NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`, `role_id`),
  CONSTRAINT `fk_rbac_user_roles_user` FOREIGN KEY (`user_id`) REFERENCES `rbac_users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_rbac_user_roles_role` FOREIGN KEY (`role_id`) REFERENCES `rbac_roles` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `rbac_role_permissions` (
  `role_id` BIGINT UNSIGNED NOT NULL,
  `permission_id` BIGINT UNSIGNED NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`role_id`, `permission_id`),
  CONSTRAINT `fk_rbac_role_permissions_role` FOREIGN KEY (`role_id`) REFERENCES `rbac_roles` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_rbac_role_permissions_permission` FOREIGN KEY (`permission_id`) REFERENCES `rbac_permissions` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `rbac_menus` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `title` VARCHAR(128) NOT NULL,
  `code` VARCHAR(128) NOT NULL,
  `path` VARCHAR(255) NOT NULL DEFAULT '',
  `icon` VARCHAR(64) NOT NULL DEFAULT '',
  `parent_id` BIGINT UNSIGNED NULL,
  `permission_id` BIGINT UNSIGNED NULL,
  `sort_order` INT UNSIGNED NOT NULL DEFAULT 0,
  `is_visible` TINYINT(1) NOT NULL DEFAULT 1,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_rbac_menus_code` (`code`),
  KEY `idx_rbac_menus_parent` (`parent_id`),
  CONSTRAINT `fk_rbac_menus_parent` FOREIGN KEY (`parent_id`) REFERENCES `rbac_menus` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_rbac_menus_permission` FOREIGN KEY (`permission_id`) REFERENCES `rbac_permissions` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `rbac_menu_permissions` (
  `menu_id` BIGINT UNSIGNED NOT NULL,
  `permission_id` BIGINT UNSIGNED NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`menu_id`, `permission_id`),
  CONSTRAINT `fk_rbac_menu_permissions_menu` FOREIGN KEY (`menu_id`) REFERENCES `rbac_menus` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_rbac_menu_permissions_permission` FOREIGN KEY (`permission_id`) REFERENCES `rbac_permissions` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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

INSERT INTO `rbac_roles` (`code`, `name`, `description`, `is_system`, `is_active`)
VALUES ('super_admin', '超级管理员', '拥有平台全部权限', 1, 1)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `is_active` = 1;

INSERT INTO `rbac_permissions` (`code`, `name`, `permission_type`, `description`, `is_active`)
VALUES
  ('user:list', '查看用户', 'api', '查看用户列表', 1),
  ('user:create', '创建用户', 'api', '创建用户', 1),
  ('role:list', '查看角色', 'api', '查看角色列表', 1),
  ('role:update', '更新角色', 'api', '更新角色及权限绑定', 1),
  ('permission:list', '查看权限', 'api', '查看权限点', 1),
  ('menu:list', '查看菜单', 'api', '查看菜单树', 1),
  ('menu:publish', '发布菜单', 'button', '发布菜单配置', 1),
  ('host:list', '查看机器资源信息', 'api', '查看主机列表和机器资源指标', 1),
  ('host:create', '添加机器资源主机', 'api', '添加 node-exporter 主机', 1),
  ('host:delete', '删除机器资源主机', 'api', '删除 node-exporter 主机', 1)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `is_active` = 1;

INSERT INTO `rbac_users` (`username`, `password_hash`, `display_name`, `email`, `is_active`, `is_superuser`)
VALUES ('admin', '$2b$12$NHupqxLWxdloX2JrB.nraeuRy/X5wFdW5nTxb.xN4NTKL/axWcvL2', '系统管理员', '', 1, 1)
ON DUPLICATE KEY UPDATE
  `display_name` = VALUES(`display_name`),
  `is_active` = 1,
  `is_superuser` = 1;

INSERT IGNORE INTO `rbac_user_roles` (`user_id`, `role_id`)
SELECT u.id, r.id FROM `rbac_users` u, `rbac_roles` r
WHERE u.username = 'admin' AND r.code = 'super_admin';

INSERT IGNORE INTO `rbac_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `rbac_roles` r, `rbac_permissions` p
WHERE r.code = 'super_admin';

INSERT INTO `rbac_menus` (`title`, `code`, `path`, `icon`, `parent_id`, `permission_id`, `sort_order`, `is_visible`, `is_active`)
VALUES
  ('系统管理', 'system', '/system', 'settings', NULL, NULL, 10, 1, 1),
  ('用户管理', 'system.users', '/system/users', 'users', NULL, (SELECT id FROM `rbac_permissions` WHERE code = 'user:list'), 11, 1, 1),
  ('角色管理', 'system.roles', '/system/roles', 'shield', NULL, (SELECT id FROM `rbac_permissions` WHERE code = 'role:list'), 12, 1, 1),
  ('权限管理', 'system.permissions', '/system/permissions', 'key', NULL, (SELECT id FROM `rbac_permissions` WHERE code = 'permission:list'), 13, 1, 1),
  ('菜单管理', 'system.menus', '/system/menus', 'menu', NULL, (SELECT id FROM `rbac_permissions` WHERE code = 'menu:list'), 14, 1, 1),
  ('机器资源信息', 'machine.resources', '/machine-resources', 'server', NULL, (SELECT id FROM `rbac_permissions` WHERE code = 'host:list'), 20, 1, 1)
ON DUPLICATE KEY UPDATE
  `title` = VALUES(`title`),
  `path` = VALUES(`path`),
  `icon` = VALUES(`icon`),
  `permission_id` = VALUES(`permission_id`),
  `sort_order` = VALUES(`sort_order`),
  `is_visible` = VALUES(`is_visible`),
  `is_active` = VALUES(`is_active`);
