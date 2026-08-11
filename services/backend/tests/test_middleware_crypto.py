from unittest import TestCase
from unittest.mock import patch

from app import middleware_crypto


class DorisAccountCredentialCryptoTests(TestCase):
    def test_encrypts_and_decrypts_doris_account_password(self) -> None:
        with patch.object(middleware_crypto, "_encryption_key", return_value=b"k" * 32):
            ciphertext, nonce = middleware_crypto.encrypt_doris_account_password(
                "managed-secret"
            )
            plaintext = middleware_crypto.decrypt_doris_account_password(
                ciphertext, nonce
            )

        self.assertEqual(plaintext, "managed-secret")
        self.assertNotIn(b"managed-secret", ciphertext)
        self.assertEqual(len(nonce), 12)

    def test_doris_account_ciphertext_cannot_be_used_as_instance_password(self) -> None:
        with patch.object(middleware_crypto, "_encryption_key", return_value=b"k" * 32):
            ciphertext, nonce = middleware_crypto.encrypt_doris_account_password(
                "managed-secret"
            )
            with self.assertRaisesRegex(ValueError, "中间件密码解密失败"):
                middleware_crypto.decrypt_middleware_password(ciphertext, nonce)

    def test_encrypts_and_decrypts_mysql_account_password(self) -> None:
        with patch.object(middleware_crypto, "_encryption_key", return_value=b"k" * 32):
            ciphertext, nonce = middleware_crypto.encrypt_mysql_account_password(
                "mysql-managed-secret"
            )
            plaintext = middleware_crypto.decrypt_mysql_account_password(
                ciphertext, nonce
            )

        self.assertEqual(plaintext, "mysql-managed-secret")
        self.assertNotIn(b"mysql-managed-secret", ciphertext)
        self.assertEqual(len(nonce), 12)

    def test_mysql_account_ciphertext_is_domain_isolated(self) -> None:
        with patch.object(middleware_crypto, "_encryption_key", return_value=b"k" * 32):
            ciphertext, nonce = middleware_crypto.encrypt_mysql_account_password(
                "mysql-managed-secret"
            )
            with self.assertRaisesRegex(ValueError, "中间件密码解密失败"):
                middleware_crypto.decrypt_doris_account_password(ciphertext, nonce)
