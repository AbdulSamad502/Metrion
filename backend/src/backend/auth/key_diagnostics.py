"""Explains a Clerk rejection that is really a KEY problem.

`CLERK_JWT_KEY` must be the instance's RSA PUBLIC key. When it is not (the `.env.example`
placeholder left in place, a truncated paste, the wrong key type), Clerk's SDK cannot even build a
verifier and every authenticated request is rejected with the same generic 401 — indistinguishable
from "not signed in". This reports the problem once at startup, and again, with the reason, on each
rejection that points at the key. Nothing here ever logs key material.
"""

from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

# `TokenVerificationErrorReason` names that mean "the configured key is the problem".
KEY_RELATED_REASONS = {
    "JWK_FAILED_TO_RESOLVE": "CLERK_JWT_KEY is not a usable RSA public key (it could not be parsed).",
    "TOKEN_INVALID_SIGNATURE": (
        "The token's signature does not match CLERK_JWT_KEY. The key is probably from a different Clerk instance "
        "than the frontend's publishable key (check both come from the SAME Clerk application / environment)."
    ),
}


def jwt_key_problem(pem: str) -> str | None:
    """Why `pem` cannot verify Clerk tokens, or None if it is a well-formed RSA public key."""
    try:
        key = serialization.load_pem_public_key(pem.encode())
    except Exception:
        return (
            "CLERK_JWT_KEY is not a valid PEM public key — is it still the .env.example placeholder, or truncated? "
            "Copy it from Clerk Dashboard -> API Keys -> Show JWT public key, as one line with \\n between lines."
        )
    if not isinstance(key, RSAPublicKey):
        return "CLERK_JWT_KEY parses, but it is not an RSA public key (Clerk session tokens are RS256)."
    return None


def key_hint(reason: object) -> str | None:
    name = getattr(reason, "name", None) or str(reason).rsplit(".", 1)[-1].upper().replace("-", "_")
    return KEY_RELATED_REASONS.get(name)
