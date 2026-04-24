from derivation_web.core.signing import generate_keypair, sign, verify


def test_roundtrip():
    priv, pub = generate_keypair()
    sig = sign(priv, "hello")
    assert verify(pub, "hello", sig) is True


def test_tampered_message_fails():
    priv, pub = generate_keypair()
    sig = sign(priv, "hello")
    assert verify(pub, "world", sig) is False


def test_wrong_key_fails():
    priv1, _ = generate_keypair()
    _, pub2 = generate_keypair()
    sig = sign(priv1, "hello")
    assert verify(pub2, "hello", sig) is False
