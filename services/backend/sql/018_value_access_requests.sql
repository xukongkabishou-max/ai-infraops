USE `infraops`;

CREATE TABLE IF NOT EXISTS value_access_requests (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  requester_id BIGINT UNSIGNED NOT NULL,
  category VARCHAR(16) NOT NULL,
  environment_name VARCHAR(128) NOT NULL,
  resource_name VARCHAR(255) NOT NULL,
  target JSON NOT NULL,
  reason VARCHAR(1000) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'pending',
  reviewer_id BIGINT UNSIGNED NULL,
  review_note VARCHAR(1000) NOT NULL DEFAULT '',
  created_at DATETIME(6) NOT NULL,
  reviewed_at DATETIME(6) NULL,
  captured_at DATETIME(6) NULL,
  expires_at DATETIME(6) NULL,
  snapshot_ciphertext MEDIUMBLOB NULL,
  snapshot_nonce VARBINARY(12) NULL,
  INDEX idx_value_owner (requester_id, category, id),
  INDEX idx_value_status (status, id),
  FOREIGN KEY (requester_id) REFERENCES rbac_users(id),
  FOREIGN KEY (reviewer_id) REFERENCES rbac_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO rbac_permissions (code, name, permission_type, description, is_active)
VALUES ('value:approve', '审批 Key 数值查看', 'api', '查看全部数值申请并批准或拒绝', 1)
ON DUPLICATE KEY UPDATE name=VALUES(name);

INSERT IGNORE INTO rbac_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM rbac_roles r JOIN rbac_permissions p ON p.code='value:approve'
WHERE r.code IN ('super_admin', 'ops');

INSERT INTO rbac_menus (title, code, path, icon, permission_id, sort_order, is_visible, is_active)
VALUES ('Key 查看审批', 'admin.value-approvals', '/#value-approvals', 'clipboard-check',
  (SELECT id FROM rbac_permissions WHERE code='value:approve'), 91, 1, 1)
ON DUPLICATE KEY UPDATE permission_id=VALUES(permission_id);
