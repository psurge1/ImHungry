"""Cognito access-token verification with injectable public-key retrieval."""

from uuid import UUID

import jwt

from .errors import AppError


class CognitoVerifier:
    def __init__(self, issuer, client_id, *, jwks_client=None):
        if not issuer.startswith("https://cognito-idp.") or not client_id:
            raise ValueError("Configure a Cognito issuer and app client ID")
        self.issuer, self.client_id = issuer.rstrip("/"), client_id
        self.jwks = jwks_client or jwt.PyJWKClient(self.issuer + "/.well-known/jwks.json", timeout=5)

    def __call__(self, token):
        try:
            key = self.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], issuer=self.issuer,
                                options={"verify_aud": False, "require": ["exp", "iat", "iss", "sub", "token_use", "client_id"]})
            if claims["token_use"] != "access" or claims["client_id"] != self.client_id:
                raise ValueError("Invalid token purpose or client")
            return str(UUID(claims["sub"]))
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise AppError("unauthorized", "A valid Cognito access token is required", 401) from None


def deny_authentication(token):
    raise AppError("auth_unconfigured", "Authentication is not configured", 503)
