"""Ed25519 signing. One keypair per actor."""

from __future__ import annotations

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def generate_keypair() -> tuple[str, str]:
    """Return (privkey_b64, pubkey_b64). 32-byte raw keys, base64-encoded."""
    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    pub_bytes = priv.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    )
    return base64.b64encode(priv_bytes).decode(), base64.b64encode(pub_bytes).decode()


def sign(privkey_b64: str, message: str) -> str:
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(privkey_b64))
    sig = priv.sign(message.encode("utf-8"))
    return base64.b64encode(sig).decode()


def verify(pubkey_b64: str, message: str, signature_b64: str) -> bool:
    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pubkey_b64))
    try:
        pub.verify(base64.b64decode(signature_b64), message.encode("utf-8"))
    except InvalidSignature:
        return False
    return True
