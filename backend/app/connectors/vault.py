"""
Secure credential storage using Fernet (AES) encryption.

Credentials are encrypted before storage and never logged in plaintext.
"""

import os
import base64
import hashlib
import json
import logging
from typing import Dict, Any, Optional
from cryptography.fernet import Fernet
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _coerce_fernet_key(key) -> bytes:
    """Valid Fernet key: an already-valid key passes through (preserves existing
    ciphertext); any other string is deterministically derived (SHA-256 → urlsafe b64)."""
    kb = key.encode() if isinstance(key, str) else key
    try:
        Fernet(kb)
        return kb
    except Exception:
        return base64.urlsafe_b64encode(hashlib.sha256(kb).digest())


class CredentialVault:
    """
    Secure vault for storing connector credentials.

    Uses Fernet (symmetric AES encryption) to encrypt credentials before storage.
    Encryption key must be provided via ENCRYPTION_KEY environment variable.
    """

    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize credential vault.

        Args:
            encryption_key: Fernet key or arbitrary string (derived via SHA-256).
                If None, reads from ENCRYPTION_KEY env var.

        Raises:
            ValueError: If no key is available and ENVIRONMENT=production (fail-closed).
        """
        from app.runtime import is_production
        key = encryption_key or os.getenv("ENCRYPTION_KEY")
        if not key:
            if is_production():
                raise ValueError(
                    "ENCRYPTION_KEY is required in production (ENVIRONMENT=production)."
                )
            logger.warning(
                "ENCRYPTION_KEY unset — using an insecure local-dev key. NOT for production."
            )
            key = "datapond-local-dev-encryption-key"
        self.cipher = Fernet(_coerce_fernet_key(key))

    def encrypt_credentials(self, credentials: Dict[str, Any]) -> str:
        """
        Encrypt connection credentials.

        Args:
            credentials: Dictionary containing credentials (passwords, tokens, etc.)

        Returns:
            Base64-encoded encrypted credentials string

        Example:
            >>> vault = CredentialVault()
            >>> encrypted = vault.encrypt_credentials({
            ...     "host": "db.example.com",
            ...     "username": "admin",
            ...     "password": "secret123"
            ... })
        """
        try:
            # Convert to JSON string
            plaintext = json.dumps(credentials, sort_keys=True)

            # Encrypt
            encrypted_bytes = self.cipher.encrypt(plaintext.encode('utf-8'))

            # Return as string
            return encrypted_bytes.decode('utf-8')

        except Exception as e:
            logger.error(f"Failed to encrypt credentials: {e}")
            raise ValueError(f"Encryption failed: {e}")

    def decrypt_credentials(self, encrypted: str) -> Dict[str, Any]:
        """
        Decrypt connection credentials.

        Args:
            encrypted: Base64-encoded encrypted credentials string

        Returns:
            Dictionary containing decrypted credentials

        Raises:
            ValueError: If decryption fails (invalid key or corrupted data)

        Example:
            >>> vault = CredentialVault()
            >>> credentials = vault.decrypt_credentials(encrypted_string)
            >>> print(credentials["host"])
        """
        try:
            # Decrypt
            decrypted_bytes = self.cipher.decrypt(encrypted.encode('utf-8'))

            # Parse JSON
            plaintext = decrypted_bytes.decode('utf-8')
            credentials = json.loads(plaintext)

            return credentials

        except Exception as e:
            logger.error("Failed to decrypt credentials (incorrect key or corrupted data)")
            raise ValueError(f"Decryption failed: {e}")

    def rotate_key(self, old_key: str, new_key: str, encrypted_data: str) -> str:
        """
        Rotate encryption key by decrypting with old key and encrypting with new key.

        Args:
            old_key: Old encryption key
            new_key: New encryption key
            encrypted_data: Data encrypted with old key

        Returns:
            Data encrypted with new key

        Example:
            >>> vault = CredentialVault()
            >>> new_encrypted = vault.rotate_key(
            ...     old_key="old_key_base64",
            ...     new_key="new_key_base64",
            ...     encrypted_data=old_encrypted
            ... )
        """
        # Decrypt with old key
        old_vault = CredentialVault(encryption_key=old_key)
        credentials = old_vault.decrypt_credentials(encrypted_data)

        # Encrypt with new key
        new_vault = CredentialVault(encryption_key=new_key)
        return new_vault.encrypt_credentials(credentials)

    @staticmethod
    def generate_key() -> str:
        """
        Generate a new Fernet encryption key.

        Returns:
            Base64-encoded encryption key as string

        Example:
            >>> key = CredentialVault.generate_key()
            >>> print(f"ENCRYPTION_KEY={key}")
        """
        return Fernet.generate_key().decode('utf-8')

    @staticmethod
    def mask_credentials(credentials: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mask sensitive fields for logging.

        Args:
            credentials: Credentials dictionary

        Returns:
            Dictionary with sensitive fields masked

        Example:
            >>> masked = CredentialVault.mask_credentials({
            ...     "host": "db.example.com",
            ...     "username": "admin",
            ...     "password": "secret123",
            ...     "token": "abc123def456"
            ... })
            >>> print(masked)
            {"host": "db.example.com", "username": "admin", "password": "***", "token": "***"}
        """
        sensitive_fields = {
            "password", "secret", "token", "api_key", "access_key",
            "secret_key", "private_key", "credentials", "auth"
        }

        masked = {}
        for key, value in credentials.items():
            # Check if field name contains sensitive keywords
            is_sensitive = any(field in key.lower() for field in sensitive_fields)

            if is_sensitive:
                masked[key] = "***" if value else None
            else:
                masked[key] = value

        return masked


class EncryptedCredential(BaseModel):
    """Model for storing encrypted credentials"""
    connection_id: str = Field(..., description="Unique connection identifier")
    encrypted_data: str = Field(..., description="Encrypted credentials blob")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    key_version: int = Field(default=1, description="Encryption key version for rotation")


# Example usage in logging
class SecureLogger:
    """Logger that automatically masks credentials"""

    @staticmethod
    def log_connection_attempt(credentials: Dict[str, Any]):
        """Log connection attempt with masked credentials"""
        masked = CredentialVault.mask_credentials(credentials)
        logger.info(f"Attempting connection with config: {masked}")

    @staticmethod
    def log_error(message: str, credentials: Dict[str, Any]):
        """Log error with masked credentials"""
        masked = CredentialVault.mask_credentials(credentials)
        logger.error(f"{message} | Config: {masked}")
