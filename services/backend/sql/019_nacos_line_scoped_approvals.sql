USE `infraops`;

UPDATE value_access_requests
SET status='invalidated', snapshot_ciphertext=NULL, snapshot_nonce=NULL,
    review_note='整份配置查看授权已停用，请重新获取结构并按行号申请'
WHERE category='nacos'
  AND (JSON_EXTRACT(target, '$.scope_version') IS NULL
       OR JSON_UNQUOTE(JSON_EXTRACT(target, '$.scope_version')) <> '1');
