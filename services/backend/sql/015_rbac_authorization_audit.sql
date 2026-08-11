USE `infraops`;

INSERT INTO `rbac_roles` (`code`, `name`, `description`, `is_system`, `is_active`)
VALUES
  ('ops', '运维', '可访问全部运维功能和后台资源管理页面', 1, 1),
  ('rd', '研发', '可访问业务系统管理和中间件系统管理查询功能', 1, 1)
ON DUPLICATE KEY UPDATE
  `name` = VALUES(`name`),
  `description` = VALUES(`description`),
  `is_active` = 1;

INSERT INTO `rbac_permissions` (`code`, `name`, `permission_type`, `description`, `is_active`)
VALUES
  ('admin:console:access', '访问后台管理页面', 'page', '登录并访问后台管理页面', 1),
  ('audit:list', '查看安全审计日志', 'api', '查询登录、鉴权和受保护接口访问记录', 1),
  ('page:machine:view', '查看机器信息管理', 'page', '查看机器指标、Linux 账号和数据库账号页面', 1),
  ('page:business:view', '查看业务系统管理', 'page', '查看 NodePort、镜像、GPU 和环境变量 Key 页面', 1),
  ('page:middleware:view', '查看中间件系统管理', 'page', '查看 Nacos 配置目录和中间件可用性页面', 1),
  ('page:monitoring:view', '查看监控系统集成', 'page', '查看监控系统集成页面', 1),
  ('host:update', '修改机器资源主机', 'api', '修改主机、Agent、K8S 凭证及 Namespace 白名单', 1),
  ('host:probe', '检测机器资源主机', 'api', '重新检测 node-exporter 连接', 1),
  ('nacos:config-structure:read', '查看 Nacos 脱敏配置结构', 'api', '读取 YAML/JSON 后仅返回清空 value 的结构', 1),
  ('middleware:health:execute', '执行中间件可用性校验', 'api', '执行 MySQL、Doris、Redis 和 Kafka 可用性校验', 1)
ON DUPLICATE KEY UPDATE
  `name` = VALUES(`name`),
  `permission_type` = VALUES(`permission_type`),
  `description` = VALUES(`description`),
  `is_active` = 1;

INSERT INTO `rbac_users` (`username`, `password_hash`, `display_name`, `email`, `is_active`, `is_superuser`)
VALUES
  ('csk', '$2b$12$M4fC1wps5IRzaPZkrtNGGO8FXs7pTOoSElTHmM7SE3bIjoveA5jA6', '运维测试用户', '', 1, 0),
  ('jiangjun', '$2b$12$4tA6cLIrdpUilzBWgg1ax.lxrkAit/xmSgRxmERRxV4qQ.edwWICm', '研发测试用户', '', 1, 0)
ON DUPLICATE KEY UPDATE
  `password_hash` = VALUES(`password_hash`),
  `display_name` = VALUES(`display_name`),
  `is_active` = 1,
  `is_superuser` = 0;

DELETE ur
FROM `rbac_user_roles` ur
JOIN `rbac_users` u ON u.id = ur.user_id
WHERE u.username IN ('csk', 'jiangjun');

INSERT INTO `rbac_user_roles` (`user_id`, `role_id`)
SELECT u.id, r.id
FROM `rbac_users` u
JOIN `rbac_roles` r ON r.code = CASE u.username WHEN 'csk' THEN 'ops' ELSE 'rd' END
WHERE u.username IN ('csk', 'jiangjun');

INSERT IGNORE INTO `rbac_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id
FROM `rbac_roles` r
JOIN `rbac_permissions` p ON p.is_active = 1
WHERE r.code IN ('super_admin', 'ops');

DELETE rp
FROM `rbac_role_permissions` rp
JOIN `rbac_roles` r ON r.id = rp.role_id
WHERE r.code = 'rd';

INSERT INTO `rbac_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id
FROM `rbac_roles` r
JOIN `rbac_permissions` p ON p.code IN (
  'page:business:view',
  'page:middleware:view',
  'k8s:nodeport:list',
  'k8s:image:list',
  'k8s:env:list',
  'nacos:catalog:list',
  'nacos:config-structure:read',
  'middleware:health:execute'
)
WHERE r.code = 'rd';

INSERT INTO `rbac_menus` (`title`, `code`, `path`, `icon`, `parent_id`, `permission_id`, `sort_order`, `is_visible`, `is_active`)
VALUES
  ('机器信息管理', 'portal.machine', '/#machine', 'server', NULL, (SELECT id FROM `rbac_permissions` WHERE code = 'page:machine:view'), 100, 1, 1),
  ('业务系统管理', 'portal.business', '/#business', 'boxes', NULL, (SELECT id FROM `rbac_permissions` WHERE code = 'page:business:view'), 110, 1, 1),
  ('中间件系统管理', 'portal.middleware', '/#middleware', 'database', NULL, (SELECT id FROM `rbac_permissions` WHERE code = 'page:middleware:view'), 120, 1, 1),
  ('监控系统集成', 'portal.monitoring', '/#monitoring', 'activity', NULL, (SELECT id FROM `rbac_permissions` WHERE code = 'page:monitoring:view'), 130, 1, 1),
  ('后台管理', 'admin.console', '/', 'settings', NULL, (SELECT id FROM `rbac_permissions` WHERE code = 'admin:console:access'), 200, 0, 1)
ON DUPLICATE KEY UPDATE
  `title` = VALUES(`title`),
  `path` = VALUES(`path`),
  `icon` = VALUES(`icon`),
  `permission_id` = VALUES(`permission_id`),
  `sort_order` = VALUES(`sort_order`),
  `is_visible` = VALUES(`is_visible`),
  `is_active` = VALUES(`is_active`);

UPDATE `rbac_menus`
SET `permission_id` = (SELECT id FROM `rbac_permissions` WHERE code = 'admin:console:access')
WHERE `code` = 'system';

CREATE TABLE IF NOT EXISTS `rbac_audit_events` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `request_id` VARCHAR(64) NOT NULL DEFAULT '',
  `actor_user_id` BIGINT UNSIGNED NULL,
  `actor_username` VARCHAR(64) NOT NULL DEFAULT '',
  `role_codes` JSON NULL,
  `client_type` VARCHAR(64) NOT NULL DEFAULT '',
  `action` VARCHAR(128) NOT NULL,
  `permission_code` VARCHAR(128) NOT NULL DEFAULT '',
  `resource_type` VARCHAR(64) NOT NULL DEFAULT '',
  `resource_id` VARCHAR(255) NOT NULL DEFAULT '',
  `request_method` VARCHAR(16) NOT NULL DEFAULT '',
  `request_path` VARCHAR(512) NOT NULL DEFAULT '',
  `result` ENUM('success','denied','error') NOT NULL,
  `status_code` SMALLINT UNSIGNED NOT NULL,
  `source_ip` VARCHAR(64) NOT NULL DEFAULT '',
  `user_agent` VARCHAR(512) NOT NULL DEFAULT '',
  `details` JSON NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_rbac_audit_actor_created` (`actor_user_id`, `created_at`),
  KEY `idx_rbac_audit_permission_created` (`permission_code`, `created_at`),
  KEY `idx_rbac_audit_result_created` (`result`, `created_at`),
  KEY `idx_rbac_audit_request_id` (`request_id`),
  CONSTRAINT `fk_rbac_audit_actor`
    FOREIGN KEY (`actor_user_id`) REFERENCES `rbac_users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
