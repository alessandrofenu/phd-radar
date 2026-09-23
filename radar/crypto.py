"""Password-based encryption shared with the dashboard (PBKDF2-SHA256 + AES-256-GCM over gzip'd JSON)."""
import base64
import gzip
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERATIONS = 400_000


def _key(password, salt, iterations):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def encrypt(obj, password) -> bytes:
    salt, iv = os.urandom(16), os.urandom(12)
    plain = gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    ct = AESGCM(_key(password, salt, ITERATIONS)).encrypt(iv, plain, None)
    env = {"v": 1, "iter": ITERATIONS, "salt": base64.b64encode(salt).decode(),
           "iv": base64.b64encode(iv).decode(), "data": base64.b64encode(ct).decode()}
    return json.dumps(env).encode()


def decrypt(blob: bytes, password):
    env = json.loads(blob)
    salt, iv = base64.b64decode(env["salt"]), base64.b64decode(env["iv"])
    plain = AESGCM(_key(password, salt, env["iter"])).decrypt(iv, base64.b64decode(env["data"]), None)
    return json.loads(gzip.decompress(plain))
