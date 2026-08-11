USE `infraops`;

INSERT INTO `rbac_permissions` (`code`, `name`, `permission_type`, `description`, `is_active`)
VALUES
  ('doris:accounts:list', '查看 Doris 账号', 'api', '查看 Doris 用户标识、角色和授权范围', 1)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `is_active` = 1;

INSERT IGNORE INTO `rbac_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `rbac_roles` r, `rbac_permissions` p
WHERE r.code = 'super_admin' AND p.code = 'doris:accounts:list';
