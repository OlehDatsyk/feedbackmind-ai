"""Feedback source integrations.

Implemented (no third-party credentials needed):
* ``rest_api`` - authenticated REST ingestion with a workspace API key (``X-API-Key``), stored as a SHA-256 hash.
* ``webhook``  - signed webhooks: HMAC-SHA256 over ``"<timestamp>.<raw body>"`` with a per-integration secret that is
  encrypted at rest (it must be recoverable to verify signatures). Requests older than 5 minutes are rejected.

Catalogued but NOT implemented: Shopify, Trustpilot, Google Business Profile, Zendesk, Intercom. They are listed with
the credentials and permissions a real connector would need; the application never simulates a connection.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

PROVIDER_CATALOG = [
    {
        "provider": "rest_api",
        "name": "REST API ingestion",
        "status": "available",
        "description": "Push feedback from your own systems with an API key.",
        "requirements": ["A workspace admin creates an API key here (shown once)."],
    },
    {
        "provider": "webhook",
        "name": "Signed webhook",
        "status": "available",
        "description": "Receive feedback from any system that can send an HMAC-signed HTTP POST.",
        "requirements": ["ENCRYPTION_KEY must be configured on the server to store the signing secret."],
    },
    {
        "provider": "shopify",
        "name": "Shopify",
        "status": "not_implemented",
        "description": "Product reviews are provided by third-party Shopify review apps, each with its own API.",
        "requirements": [
            "A Shopify custom app with read access to the chosen review app's data",
            "The review app's API credentials",
            "A connector for that review app (not included)",
        ],
    },
    {
        "provider": "trustpilot",
        "name": "Trustpilot",
        "status": "not_implemented",
        "description": "Service and product reviews via the Trustpilot Business API.",
        "requirements": ["Trustpilot Business account with API access", "API key and secret", "Business unit ID", "A connector (not included)"],
    },
    {
        "provider": "google_business_profile",
        "name": "Google Business Profile",
        "status": "not_implemented",
        "description": "Location reviews via the Google Business Profile APIs.",
        "requirements": [
            "Approved Google Business Profile API access for your Google Cloud project",
            "OAuth 2.0 client with the business.manage scope",
            "Account and location IDs",
            "A connector (not included)",
        ],
    },
    {
        "provider": "zendesk",
        "name": "Zendesk",
        "status": "not_implemented",
        "description": "Support tickets and CSAT comments via the Zendesk Support API.",
        "requirements": ["Zendesk subdomain", "API token or OAuth client with read access to tickets and satisfaction ratings", "A connector (not included)"],
    },
    {
        "provider": "intercom",
        "name": "Intercom",
        "status": "not_implemented",
        "description": "Conversations and ratings via the Intercom REST API.",
        "requirements": ["Intercom app with an access token that can read conversations", "A connector (not included)"],
    },
]

SIGNATURE_TOLERANCE_SECONDS = 300


def new_api_key() -> tuple[str, str, str]:
    """Return (plaintext key, prefix, sha256 hash). The plaintext is shown once and never stored."""
    key = "fm_live_" + secrets.token_urlsafe(32)
    return key, key[:12], hashlib.sha256(key.encode()).hexdigest()


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_webhook_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


def verify_signature(secret: str, timestamp: str | None, signature: str | None, body: bytes, now: float | None = None) -> str | None:
    """Return an error message, or None when the signature is valid and fresh."""
    if not timestamp or not signature:
        return "Missing X-FeedbackMind-Timestamp or X-FeedbackMind-Signature header."
    try:
        ts = int(timestamp)
    except ValueError:
        return "Invalid timestamp."
    if abs((now or time.time()) - ts) > SIGNATURE_TOLERANCE_SECONDS:
        return "Timestamp is too old or in the future."
    if not hmac.compare_digest(sign(secret, timestamp, body), signature.strip()):
        return "Invalid signature."
    return None
