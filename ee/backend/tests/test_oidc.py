"""Unit tests for the /ee OIDC protocol client (pure parts — no network)."""
import base64
import hashlib
import time

import pytest
from jose import jwt as jose_jwt
from jose.backends import RSAKey  # noqa: F401  (cryptography backend present)
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from ee.sso.oidc import OIDCError, make_pkce, verify_claims


# ── local RSA key + JWKS fixtures ──────────────────────────────────────────────
@pytest.fixture(scope="module")
def rsa_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = key.public_key().public_numbers()

    def b64u(i: int, length: int) -> str:
        return base64.urlsafe_b64encode(i.to_bytes(length, "big")).rstrip(b"=").decode()

    jwks = {"keys": [{
        "kty": "RSA", "use": "sig", "kid": "test-key", "alg": "RS256",
        "n": b64u(pub.n, 256), "e": b64u(pub.e, 3),
    }]}
    return priv_pem, jwks


ISS, AUD, NONCE = "https://idp.example.com", "datapond-client", "nonce-123"


def _token(priv_pem, *, iss=ISS, aud=AUD, nonce=NONCE, exp_delta=3600,
           alg="RS256", kid="test-key", extra=None):
    claims = {"iss": iss, "aud": aud, "sub": "user-1", "nonce": nonce,
              "exp": int(time.time()) + exp_delta, "iat": int(time.time()),
              "preferred_username": "alice", "email": "alice@example.com"}
    claims.update(extra or {})
    return jose_jwt.encode(claims, priv_pem, algorithm=alg, headers={"kid": kid})


def _verify(tok, jwks, **kw):
    args = dict(issuer=ISS, client_id=AUD, nonce=NONCE)
    args.update(kw)
    return verify_claims(tok, jwks, **args)


def test_valid_token_returns_claims(rsa_keypair):
    priv, jwks = rsa_keypair
    claims = _verify(_token(priv), jwks)
    assert claims["sub"] == "user-1"
    assert claims["preferred_username"] == "alice"


def test_expired_token_rejected(rsa_keypair):
    priv, jwks = rsa_keypair
    with pytest.raises(OIDCError):
        _verify(_token(priv, exp_delta=-120), jwks)


def test_wrong_audience_rejected(rsa_keypair):
    priv, jwks = rsa_keypair
    with pytest.raises(OIDCError):
        _verify(_token(priv, aud="other-client"), jwks)


def test_wrong_issuer_rejected(rsa_keypair):
    priv, jwks = rsa_keypair
    with pytest.raises(OIDCError):
        _verify(_token(priv, iss="https://evil.example.com"), jwks)


def test_wrong_nonce_rejected(rsa_keypair):
    priv, jwks = rsa_keypair
    with pytest.raises(OIDCError):
        _verify(_token(priv, nonce="stolen"), jwks)


def test_hs256_alg_confusion_rejected(rsa_keypair):
    _, jwks = rsa_keypair
    forged = jose_jwt.encode(
        {"iss": ISS, "aud": AUD, "sub": "user-1", "nonce": NONCE,
         "exp": int(time.time()) + 3600},
        "shared-secret", algorithm="HS256", headers={"kid": "test-key"})
    with pytest.raises(OIDCError):
        _verify(forged, jwks)


def test_unknown_kid_rejected(rsa_keypair):
    priv, jwks = rsa_keypair
    with pytest.raises(OIDCError):
        _verify(_token(priv, kid="rotated-away"), jwks)


def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = make_pkce()
    expect = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expect
    assert 43 <= len(verifier) <= 128


def test_state_store_single_use(monkeypatch):
    import asyncio
    from ee.sso import oidc
    monkeypatch.setattr(oidc, "_redis_client", lambda: None)  # force memory fallback
    asyncio.run(oidc.state_put("s1", {"nonce": "n", "verifier": "v"}))
    assert asyncio.run(oidc.state_pop("s1")) == {"nonce": "n", "verifier": "v"}
    assert asyncio.run(oidc.state_pop("s1")) is None      # single-use
    assert asyncio.run(oidc.state_pop("nope")) is None    # unknown
