USE `infraops`;

SET @middleware_dashboard_url_sql = IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE()
     AND TABLE_NAME = 'middleware_instances'
     AND COLUMN_NAME = 'dashboard_url') = 0,
  'ALTER TABLE `middleware_instances` ADD COLUMN `dashboard_url` VARCHAR(2048) NULL AFTER `exporter_url`',
  'SELECT 1'
);
PREPARE middleware_dashboard_url_statement FROM @middleware_dashboard_url_sql;
EXECUTE middleware_dashboard_url_statement;
DEALLOCATE PREPARE middleware_dashboard_url_statement;

INSERT INTO `rbac_permissions` (`code`, `name`, `permission_type`, `description`, `is_active`)
VALUES
  ('middleware:update', '修改中间件实例', 'api', '修改中间件连接信息和仪表盘地址', 1),
  ('mysql:dashboard:view', '查看 MySQL 仪表盘', 'api', '查看已配置的 MySQL Grafana 仪表盘', 1)
ON DUPLICATE KEY UPDATE
  `name` = VALUES(`name`),
  `permission_type` = VALUES(`permission_type`),
  `description` = VALUES(`description`),
  `is_active` = 1;

INSERT IGNORE INTO `rbac_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id
FROM `rbac_roles` r
JOIN `rbac_permissions` p ON p.code = 'middleware:update'
WHERE r.code IN ('super_admin', 'ops');

INSERT IGNORE INTO `rbac_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id
FROM `rbac_roles` r
JOIN `rbac_permissions` p ON p.code = 'mysql:dashboard:view'
WHERE r.code IN ('super_admin', 'ops', 'rd');
