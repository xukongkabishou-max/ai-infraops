USE `infraops`;

SET @middleware_exporter_url_sql = IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'middleware_instances'
     AND COLUMN_NAME = 'exporter_url') = 0,
  'ALTER TABLE `middleware_instances` ADD COLUMN `exporter_url` VARCHAR(512) NULL AFTER `base_url`',
  'SELECT 1'
);
PREPARE middleware_exporter_url_statement FROM @middleware_exporter_url_sql;
EXECUTE middleware_exporter_url_statement;
DEALLOCATE PREPARE middleware_exporter_url_statement;
