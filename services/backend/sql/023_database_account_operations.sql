ALTER TABLE database_managed_accounts
  ADD COLUMN operation_id CHAR(36) NULL,
  ADD COLUMN request_digest CHAR(64) NULL,
  ADD COLUMN grant_plan JSON NULL,
  ADD COLUMN confirmed_at DATETIME(6) NULL,
  ADD UNIQUE KEY uq_db_account_operation (operation_id);
