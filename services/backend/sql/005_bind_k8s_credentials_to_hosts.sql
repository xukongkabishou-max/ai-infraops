SET @k8s_host_column_sql = IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'k8s_clusters' AND COLUMN_NAME = 'host_id') = 0,
  'ALTER TABLE `k8s_clusters` ADD COLUMN `host_id` BIGINT UNSIGNED NULL AFTER `id`',
  'SELECT 1'
);
PREPARE k8s_host_column_statement FROM @k8s_host_column_sql;
EXECUTE k8s_host_column_statement;
DEALLOCATE PREPARE k8s_host_column_statement;

SET @k8s_host_index_sql = IF(
  (SELECT COUNT(*) FROM information_schema.STATISTICS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'k8s_clusters' AND INDEX_NAME = 'uk_k8s_clusters_host_id') = 0,
  'ALTER TABLE `k8s_clusters` ADD UNIQUE KEY `uk_k8s_clusters_host_id` (`host_id`)',
  'SELECT 1'
);
PREPARE k8s_host_index_statement FROM @k8s_host_index_sql;
EXECUTE k8s_host_index_statement;
DEALLOCATE PREPARE k8s_host_index_statement;

SET @k8s_host_fk_sql = IF(
  (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
   WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'k8s_clusters' AND CONSTRAINT_NAME = 'fk_k8s_clusters_host') = 0,
  'ALTER TABLE `k8s_clusters` ADD CONSTRAINT `fk_k8s_clusters_host` FOREIGN KEY (`host_id`) REFERENCES `machine_hosts` (`id`) ON DELETE CASCADE',
  'SELECT 1'
);
PREPARE k8s_host_fk_statement FROM @k8s_host_fk_sql;
EXECUTE k8s_host_fk_statement;
DEALLOCATE PREPARE k8s_host_fk_statement;

UPDATE `k8s_clusters` c
JOIN `machine_hosts` h ON h.environment_id = c.environment_id
JOIN (
  SELECT environment_id
  FROM `machine_hosts`
  WHERE environment_id IS NOT NULL
  GROUP BY environment_id
  HAVING COUNT(*) = 1
) single_host ON single_host.environment_id = c.environment_id
JOIN (
  SELECT environment_id
  FROM `k8s_clusters`
  GROUP BY environment_id
  HAVING COUNT(*) = 1
) single_cluster ON single_cluster.environment_id = c.environment_id
SET c.host_id = h.id
WHERE c.host_id IS NULL;
