# -*- coding: utf-8 -*-
"""Хеширование паролей (PBKDF2). Полностью совместимо с v3."""
import hashlib
import hmac
import os


def _hash_password(password):
    """Возвращает безопасный PBKDF2-хеш пароля с солью."""
    if password is None:
        password = ""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 200_000)
    return salt.hex() + ':' + digest.hex()


def _verify_password(password, stored_hash):
    """Проверяет пароль против нового PBKDF2-хеша или старого SHA256-хеша."""
    if not stored_hash:
        return False
    try:
        salt_hex, digest_hex = stored_hash.split(':', 1)
        salt = bytes.fromhex(salt_hex)
        expected = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 200_000)
        return hmac.compare_digest(expected.hex(), digest_hex)
    except ValueError:
        return stored_hash == hashlib.sha256(password.encode('utf-8')).hexdigest()