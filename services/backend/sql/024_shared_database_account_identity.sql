ALTER TABLE database_managed_accounts
  ADD UNIQUE KEY uq_db_physical_account (instance_fingerprint,user_identity);
