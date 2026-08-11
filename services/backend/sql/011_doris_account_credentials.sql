USE `infraops`;

CREATE TABLE IF NOT EXISTS `doris_account_credentials` (
  `middleware_instance_id` BIGINT UNSIGNED NOT NULL,
  `user_identity` VARCHAR(512) NOT NULL,
  `password_ciphertext` VARBINARY(4096) NOT NULL,
  `password_nonce` VARBINARY(12) NOT NULL,
  `last_action` VARCHAR(32) NOT NULL,
  `updated_by` BIGINT UNSIGNED NULL,
  `last_verified_at` DATETIME NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`middleware_instance_id`, `user_identity`),
  KEY `idx_doris_account_credentials_updated_by` (`updated_by`),
  CONSTRAINT `fk_doris_account_credentials_instance`
    FOREIGN KEY (`middleware_instance_id`) REFERENCES `middleware_instances` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_doris_account_credentials_updated_by`
    FOREIGN KEY (`updated_by`) REFERENCES `rbac_users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `doris_account_credential_audit` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `middleware_instance_id` BIGINT UNSIGNED NOT NULL,
  `user_identity` VARCHAR(512) NOT NULL,
  `action` VARCHAR(32) NOT NULL,
  `operator_user_id` BIGINT UNSIGNED NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_doris_credential_audit_instance_user` (`middleware_instance_id`, `user_identity`),
  KEY `idx_doris_credential_audit_created_at` (`created_at`),
  CONSTRAINT `fk_doris_credential_audit_instance`
    FOREIGN KEY (`middleware_instance_id`) REFERENCES `middleware_instances` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_doris_credential_audit_operator`
    FOREIGN KEY (`operator_user_id`) REFERENCES `rbac_users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
