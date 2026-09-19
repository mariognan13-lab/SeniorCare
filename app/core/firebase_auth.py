"""
Firebase ID token verification.

The Android client authenticates with the Firebase client SDK and then sends
the resulting Firebase ID token as its Bearer credential. This module verifies
those tokens against Google's rotating public certificates — the same
mechanism the Firebase Admin SDK uses internally — so no service-account key
is required.

If a service-account JSON is added later, this can be swapped for
``firebase_admin.auth.verify_id_token()`` without changing call sites.
"""

import time
from typing import Any

import httpx
from cryptography.x509 import load_pem_x509_certificate
from jose import jwt
from jose.exceptions import JWTError

from app.core.config import settings

# Google's public certificates for Firebase ID tokens.
_SECURE_TOKEN_CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/"
    "securetoken@system.gserviceaccount.com"
)

# Signing certs rotate; cache in-process and refetch on an unknown key id.
_CERT_TTL_SECONDS = 3600
_cert_cache: dict[str, str] = {}
_cert_cache_expires_at: float = 0.0


def invalidate_cert_cache() -> None:
    """Force the next verification to refetch Google's signing certificates."""
    global _cert_cache_expires_at
    _cert_cache_expires_at = 0.0


async def _get_signing_certs() -> dict[str, str]:
    """Fetch Google's ID-token signing certificates, cached in-process."""
    global _cert_cache, _cert_cache_expires_at

    if _cert_cache and time.time() < _cert_cache_expires_at:
        return _cert_cache

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(_SECURE_TOKEN_CERTS_URL)
        response.raise_for_status()
        _cert_cache = response.json()

    _cert_cache_expires_at = time.time() + _CERT_TTL_SECONDS
    return _cert_cache


async def verify_firebase_id_token(token: str) -> dict[str, Any] | None:
    """
    Verify a Firebase ID token and return its claims, or None if invalid.

    Validates the RS256 signature against Google's public certificates, plus
    the token's audience, issuer, and expiry.
    """
    project_id = settings.FIREBASE_PROJECT_ID
    if not project_id:
        return None

    try:
        headers = jwt.get_unverified_header(token)
    except JWTError:
        return None

    kid = headers.get("kid")
    if not kid:
        return None

    try:
        certs = await _get_signing_certs()
        cert_pem = certs.get(kid)
        if not cert_pem:
            # Key id unknown — the certificates may have rotated. Refetch once.
            invalidate_cert_cache()
            certs = await _get_signing_certs()
            cert_pem = certs.get(kid)
        if not cert_pem:
            return None
    except Exception:
        # Network/parse failure: treat as unverifiable rather than propagating,
        # so the caller can fall back to other credential types.
        return None

    try:
        public_key = load_pem_x509_certificate(cert_pem.encode()).public_key()
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=project_id,
            issuer=f"https://securetoken.google.com/{project_id}",
        )
    except Exception:
        return None

    # `sub` is the Firebase UID and is required by the spec.
    if not claims.get("sub"):
        return None

    return claims
