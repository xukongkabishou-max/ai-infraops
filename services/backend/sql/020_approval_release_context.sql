USE `infraops`;

SET @approval_ticket_sql = IF(
  EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE()
    AND table_name='value_access_requests' AND column_name='release_ticket'),
  'SELECT 1',
  'ALTER TABLE value_access_requests ADD COLUMN release_ticket VARCHAR(200) NOT NULL DEFAULT '''''
);
PREPARE approval_context_stmt FROM @approval_ticket_sql;
EXECUTE approval_context_stmt;
DEALLOCATE PREPARE approval_context_stmt;

SET @approval_version_sql = IF(
  EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE()
    AND table_name='value_access_requests' AND column_name='release_version'),
  'SELECT 1',
  'ALTER TABLE value_access_requests ADD COLUMN release_version VARCHAR(200) NOT NULL DEFAULT '''''
);
PREPARE approval_context_stmt FROM @approval_version_sql;
EXECUTE approval_context_stmt;
DEALLOCATE PREPARE approval_context_stmt;
