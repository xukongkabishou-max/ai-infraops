SET @credential_name_sql = IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'k8s_clusters' AND COLUMN_NAME = 'credential_name') = 0,
  'ALTER TABLE `k8s_clusters` ADD COLUMN `credential_name` VARCHAR(255) NOT NULL DEFAULT '''' AFTER `credential_ref`',
  'SELECT 1'
);
PREPARE credential_name_statement FROM @credential_name_sql;
EXECUTE credential_name_statement;
DEALLOCATE PREPARE credential_name_statement;

SET @credential_ciphertext_sql = IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'k8s_clusters' AND COLUMN_NAME = 'credential_ciphertext') = 0,
  'ALTER TABLE `k8s_clusters` ADD COLUMN `credential_ciphertext` MEDIUMBLOB NULL AFTER `credential_name`',
  'SELECT 1'
);
PREPARE credential_ciphertext_statement FROM @credential_ciphertext_sql;
EXECUTE credential_ciphertext_statement;
DEALLOCATE PREPARE credential_ciphertext_statement;

SET @credential_nonce_sql = IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'k8s_clusters' AND COLUMN_NAME = 'credential_nonce') = 0,
  'ALTER TABLE `k8s_clusters` ADD COLUMN `credential_nonce` VARBINARY(12) NULL AFTER `credential_ciphertext`',
  'SELECT 1'
);
PREPARE credential_nonce_statement FROM @credential_nonce_sql;
EXECUTE credential_nonce_statement;
DEALLOCATE PREPARE credential_nonce_statement;

SET @credential_fingerprint_sql = IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'k8s_clusters' AND COLUMN_NAME = 'credential_fingerprint') = 0,
  'ALTER TABLE `k8s_clusters` ADD COLUMN `credential_fingerprint` CHAR(64) NOT NULL DEFAULT '''' AFTER `credential_nonce`',
  'SELECT 1'
);
PREPARE credential_fingerprint_statement FROM @credential_fingerprint_sql;
EXECUTE credential_fingerprint_statement;
DEALLOCATE PREPARE credential_fingerprint_statement;
