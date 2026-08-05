USE `infraops`;

SET @namespace_keys_column_exists = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'machine_hosts'
    AND COLUMN_NAME = 'namespace_keys'
);
SET @add_namespace_keys_sql = IF(
  @namespace_keys_column_exists = 0,
  'ALTER TABLE `machine_hosts` ADD COLUMN `namespace_keys` JSON NULL AFTER `node_exporter_url`',
  'SELECT 1'
);
PREPARE add_namespace_keys_statement FROM @add_namespace_keys_sql;
EXECUTE add_namespace_keys_statement;
DEALLOCATE PREPARE add_namespace_keys_statement;

INSERT INTO `rbac_permissions` (`code`, `name`, `permission_type`, `description`, `is_active`)
VALUES
  ('k8s:env:list', '查看 K8S 环境变量 Key', 'api', '查看白名单 namespace 下容器运行时环境变量名称', 1)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `is_active` = 1;

INSERT IGNORE INTO `rbac_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `rbac_roles` r, `rbac_permissions` p
WHERE r.code = 'super_admin' AND p.code = 'k8s:env:list';
