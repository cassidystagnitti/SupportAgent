from __future__ import annotations

import base64
import hashlib
import hmac


def verify_helpscout_webhook_signature(secret: str, raw_body: bytes, signature_header: str | None) -> bool:
    """
    Validate X-HelpScout-Signature using the shared webhook secret.

    Per Help Scout: HMAC-SHA1 of the **raw** request body, Base64-encoded, compared to the header.
    """
    if not secret or not signature_header:
        return False
    mac = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha1).digest()
    expected = base64.b64encode(mac).decode("ascii")
    return hmac.compare_digest(expected.strip(), signature_header.strip())
