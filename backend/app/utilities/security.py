"""Token verification and the two authorization decisions."""

from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from app.constants import Settings, normalize_email
from app.core import Forbidden, Unauthorized


@dataclass
class Identity:
    """Claims taken from a Supabase access token. The provider is not one of them."""

    user_id: str
    email: str
    email_verified: bool


@dataclass
class Principal:
    """The app user for this request. Role comes from our table, not the token."""

    user_id: str
    email: str
    email_verified: bool
    role: str
    signup_role: str
    org_id: str | None
    disabled: bool
    graph_name: str | None
    graph_status: str | None

    @property
    def ready(self) -> bool:
        return self.graph_status == "ready" and not self.disabled


class SupabaseTokenVerifier:
    """Verify Supabase access tokens from the public JWKS. Email, Google, and GitHub share this path."""

    algorithms = ["ES256", "RS256", "EdDSA"]

    def __init__(self, issuer: str, audience: str, jwks_url: str = "", keys: dict | None = None):
        self.issuer = issuer
        self.audience = audience
        self._keys = keys or {}
        self._jwks = PyJWKClient(jwks_url, cache_keys=True, lifespan=600) if jwks_url and not keys else None

    @classmethod
    def from_settings(cls, settings: Settings) -> "SupabaseTokenVerifier":
        return cls(settings.jwt_issuer, settings.supabase_jwt_audience, jwks_url=settings.jwks_url)

    def verify(self, token: str) -> Identity:
        try:
            header = jwt.get_unverified_header(token)
            key = self._signing_key(token, header.get("kid"))
            claims = jwt.decode(
                token,
                key,
                algorithms=self.algorithms,
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise Unauthorized("invalid token", type(exc).__name__) from exc
        email = normalize_email(str(claims.get("email") or ""))
        if not email:
            raise Forbidden("the login did not include an email")
        verified = claims.get("email_verified")
        if claims.get("is_anonymous") is True or verified is False:
            raise Forbidden("email is not confirmed")
        return Identity(str(claims["sub"]), email, True)

    def _signing_key(self, token: str, kid: str | None):
        if self._keys:
            if kid not in self._keys:
                raise Unauthorized("invalid token", "unknown signing key")
            return self._keys[kid]
        if self._jwks is None:
            raise Unauthorized("invalid token", "no jwks")
        return self._jwks.get_signing_key_from_jwt(token).key


def require_admin(principal: Principal, settings: Settings) -> None:
    """Allow-list, verified token, and an enabled admin row. Each one is required."""
    if not principal.email_verified:
        raise Forbidden("email is not confirmed")
    if normalize_email(principal.email) not in settings.admin_email_set:
        raise Forbidden("not an admin")
    if principal.role != "admin" or principal.disabled or not principal.ready:
        raise Forbidden("not an admin")
