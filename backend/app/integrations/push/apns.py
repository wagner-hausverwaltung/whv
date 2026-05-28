"""Apple Push Notification service client — token-based auth.

Token-based (.p8) APNs auth, per Apple's recommended scheme:
* Sign a short-lived ES256 JWT with the .p8 auth key. The JWT
  payload is `{iss: team_id, iat: now}`; the header carries the
  Key ID (`kid`). One key works for sandbox + production + every
  app under the team.
* Cache the JWT and reuse it for up to ~50 minutes (Apple rejects
  tokens older than 1h and rate-limits regenerating them more than
  once every 20 min). We refresh at 45 min to stay clear of both.
* Send over HTTP/2 to `api.push.apple.com` (prod) or
  `api.development.push.apple.com` (sandbox). The `:path` is
  `/3/device/{token}`; headers carry `apns-topic` (bundle id),
  `apns-push-type`, `apns-priority`. Body is the aps payload.

The push *service* (`app/services/push.py`) owns recipient
resolution + dead-token pruning; this module is the thin transport.

Disabled when `apns_key_p8` is empty — `APNSClient.is_configured`
is False and callers skip. Mirrors the Resend-disabled-when-no-key
pattern so staging without the key just doesn't push.
"""

import time
from dataclasses import dataclass

import httpx
import jwt

from app.config import Settings

_PROD_HOST = "https://api.push.apple.com"
_SANDBOX_HOST = "https://api.development.push.apple.com"
# Refresh the auth JWT well before Apple's 1h hard expiry; Apple
# also rejects regenerating more than once per 20 min, so 45 min is
# the sweet spot.
_TOKEN_TTL_SECONDS = 45 * 60


class APNSError(Exception):
    """Transport-level failure (network, malformed config). Per-token
    delivery failures (400/410) are returned as APNSResult instead so
    the caller can prune dead tokens without try/except per device."""


@dataclass(slots=True)
class APNSResult:
    """Outcome of one device send. `unregistered` is the signal the
    push service uses to soft-delete a dead token (HTTP 410, or 400
    with reason BadDeviceToken / Unregistered)."""

    token: str
    ok: bool
    status_code: int
    reason: str | None = None

    @property
    def unregistered(self) -> bool:
        if self.status_code == 410:
            return True
        return self.reason in {"Unregistered", "BadDeviceToken", "DeviceTokenNotForTopic"}


class APNSClient:
    """Async APNs sender. One instance per process; the auth JWT is
    cached + refreshed lazily."""

    def __init__(self, settings: Settings) -> None:
        self._key_p8 = settings.apns_key_p8
        self._key_id = settings.apns_key_id
        self._team_id = settings.apns_team_id
        self._bundle_id = settings.apns_bundle_id
        self._host = _SANDBOX_HOST if settings.apns_use_sandbox else _PROD_HOST
        self._cached_token: str | None = None
        self._cached_at: float = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(self._key_p8 and self._key_id and self._team_id)

    def _auth_token(self) -> str:
        """Return a fresh-enough ES256 JWT, regenerating only after
        the TTL elapses. PyJWT signs with the .p8 (an EC private key
        in PEM form)."""
        now = time.time()
        if self._cached_token is not None and (now - self._cached_at) < _TOKEN_TTL_SECONDS:
            return self._cached_token
        token = jwt.encode(
            {"iss": self._team_id, "iat": int(now)},
            self._key_p8,
            algorithm="ES256",
            headers={"kid": self._key_id},
        )
        self._cached_token = token
        self._cached_at = now
        return token

    async def send(
        self,
        *,
        token: str,
        title: str,
        body: str,
        deep_link: str | None = None,
        thread_id: str | None = None,
        badge: int | None = None,
    ) -> APNSResult:
        """Deliver one alert push. `deep_link` rides in the custom
        payload (`whv` key) so the app can route the tap; `thread_id`
        groups related notifications in Notification Center (e.g. all
        comments on the same ETV)."""
        if not self.is_configured:
            return APNSResult(token=token, ok=False, status_code=0, reason="not_configured")

        aps: dict[str, object] = {
            "alert": {"title": title, "body": body},
            "sound": "default",
        }
        if badge is not None:
            aps["badge"] = badge
        if thread_id:
            aps["thread-id"] = thread_id
        payload: dict[str, object] = {"aps": aps}
        if deep_link:
            # Custom key the iOS app reads from userInfo to route the
            # tap via DeepLinkRouter.
            payload["whv"] = {"deep_link": deep_link}

        headers = {
            "authorization": f"bearer {self._auth_token()}",
            "apns-topic": self._bundle_id,
            "apns-push-type": "alert",
            "apns-priority": "10",
        }
        url = f"{self._host}/3/device/{token}"
        try:
            async with httpx.AsyncClient(http2=True, timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise APNSError(f"APNs request failed: {exc}") from exc

        if resp.status_code == 200:
            return APNSResult(token=token, ok=True, status_code=200)
        # APNs error body: {"reason": "Unregistered"}.
        reason: str | None = None
        try:
            reason = resp.json().get("reason")
        except Exception:
            reason = None
        return APNSResult(token=token, ok=False, status_code=resp.status_code, reason=reason)
