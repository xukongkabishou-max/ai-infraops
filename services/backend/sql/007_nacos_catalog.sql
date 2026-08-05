USE `infraops`;

INSERT INTO `rbac_permissions` (`code`, `name`, `permission_type`, `description`, `is_active`)
VALUES
  ('nacos:catalog:list', '查看 Nacos 配置目录', 'api', '查看 Nacos 命名空间、Group、DataId 和配置格式', 1)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `is_active` = 1;

INSERT IGNORE INTO `rbac_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `rbac_roles` r, `rbac_permissions` p
WHERE r.code = 'super_admin' AND p.code = 'nacos:catalog:list';
