"""AES-CBC segment decryption, which had no test at all.

``requirements.txt`` pinned ``cryptography==3.4.8`` for years with a comment
saying newer versions removed ``default_backend()`` and that unpinning "requires
an API change in m3u8.py". The change turned out to be deleting the argument —
but nothing in the suite ran ``decrypt_ts``, so the pin could only be lifted on
faith. A pin nobody can test is a pin nobody dares touch, which is how it
survived to version 50.

These round-trip a known key and IV so the decryption path fails loudly if the
cipher construction ever breaks again.
"""

import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.core.m3u8 import Decryption


def _encrypt(key, iv, plaintext):
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(plaintext) + encryptor.finalize()


def test_decrypts_what_was_encrypted():
    key, iv = os.urandom(16), os.urandom(16)
    plaintext = b"a transport stream, 32 bytes ok."

    decryption = Decryption(key)
    decryption.parse_key(iv.hex())

    assert decryption.decrypt_ts(_encrypt(key, iv, plaintext)) == plaintext


def test_parse_key_accepts_the_0x_prefix():
    """M3U8 playlists write the IV as ``IV=0x...``, prefix included."""
    iv = os.urandom(16)

    decryption = Decryption(os.urandom(16))
    decryption.parse_key("0x" + iv.hex())

    assert decryption.iv == iv


def test_the_wrong_key_does_not_give_the_plaintext_back():
    """Guards against a cipher that silently stops encrypting at all."""
    key, iv = os.urandom(16), os.urandom(16)
    plaintext = b"a transport stream, 32 bytes ok."

    decryption = Decryption(os.urandom(16))
    decryption.parse_key(iv.hex())

    assert decryption.decrypt_ts(_encrypt(key, iv, plaintext)) != plaintext
