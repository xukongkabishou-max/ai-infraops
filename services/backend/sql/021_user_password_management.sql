USE `infraops`;

SET @user_password_sql = IF(
  EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE()
    AND table_name='rbac_users' AND column_name='auth_version'),
  'SELECT 1',
  'ALTER TABLE rbac_users ADD COLUMN auth_version BIGINT UNSIGNED NOT NULL DEFAULT 0'
);
PREPARE user_password_stmt FROM @user_password_sql;
EXECUTE user_password_stmt;
DEALLOCATE PREPARE user_password_stmt;

SET @user_password_sql = IF(
  EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE()
    AND table_name='rbac_users' AND column_name='password_ciphertext'),
  'SELECT 1',
  'ALTER TABLE rbac_users ADD COLUMN password_ciphertext BLOB NULL, ADD COLUMN password_nonce VARBINARY(12) NULL, ADD COLUMN password_changed_at DATETIME(6) NULL'
);
PREPARE user_password_stmt FROM @user_password_sql;
EXECUTE user_password_stmt;
DEALLOCATE PREPARE user_password_stmt;

INSERT INTO rbac_permissions (code,name,permission_type,description,is_active)
VALUES ('user:password:reset','修改用户密码','api','仅当前超级管理员可重设用户密码',1),
       ('user:password:read','查看用户明文密码','api','仅 admin 超级管理员可查看已加密记录的密码',1)
ON DUPLICATE KEY UPDATE name=VALUES(name);

INSERT IGNORE INTO rbac_role_permissions (role_id,permission_id)
SELECT r.id,p.id FROM rbac_roles r JOIN rbac_permissions p
ON p.code IN ('user:password:reset','user:password:read') WHERE r.code='super_admin';
