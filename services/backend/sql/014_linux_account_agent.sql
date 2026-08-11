USE `infraops`;

SET @linux_agent_url_column_exists = (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'machine_hosts'
    AND COLUMN_NAME = 'linux_agent_url'
);
SET @add_linux_agent_url_sql = IF(
  @linux_agent_url_column_exists = 0,
  'ALTER TABLE `machine_hosts` ADD COLUMN `linux_agent_url` VARCHAR(512) NOT NULL DEFAULT '''' AFTER `node_exporter_url`',
  'SELECT 1'
);
PREPARE add_linux_agent_url_statement FROM @add_linux_agent_url_sql;
EXECUTE add_linux_agent_url_statement;
DEALLOCATE PREPARE add_linux_agent_url_statement;

INSERT INTO `rbac_permissions` (`code`, `name`, `permission_type`, `description`, `is_active`)
VALUES
  ('linux:accounts:list', '查看 Linux 账号', 'api', '通过主机 Agent 查看本地 Linux 账号列表', 1)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `is_active` = 1;

INSERT IGNORE INTO `rbac_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `rbac_roles` r, `rbac_permissions` p
WHERE r.code = 'super_admin' AND p.code = 'linux:accounts:list';
