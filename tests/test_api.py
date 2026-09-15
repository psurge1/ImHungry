from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from imhungry.api import create_app
from imhungry.auth import CognitoVerifier
from imhungry.errors import AppError
from imhungry.repository import MemoryRepository
from imhungry.services import NutritionService
from test_services import FOOD, PROFILE, NOW


@pytest.fixture
def client():
    service = NutritionService(MemoryRepository(), clock=lambda: NOW)
    return TestClient(create_app(service, verifier=lambda token: token))


def test_health_auth_validation_crud(client):
    assert client.get("/health").status_code == 200
    assert client.get("/v1/profile", headers={"X-User-ID": "alice"}).status_code == 401
    headers = {"Authorization": "Bearer alice", "Idempotency-Key": "food"}
    assert client.post("/v1/food-log", json={"user_id": "bob"}, headers=headers).status_code == 422
    response = client.post("/v1/food-log", json=FOOD, headers=headers)
    assert response.status_code == 201, response.text
    food = response.json()
    assert client.post("/v1/food-log", json=FOOD, headers=headers).json() == food
    url = "/v1/food-log/" + food["entry_ref"]
    assert client.get(url, headers={"Authorization": "Bearer bob"}).status_code == 404
    assert client.patch(url, json={"notes": "fixed"}, headers=headers).status_code == 422
    changed = client.patch(url, json={"notes": "fixed"}, headers={**headers, "If-Match": "1"})
    assert changed.status_code == 200
    assert changed.json()["version"] == 2
    assert client.patch(url, json={"notes": "stale"}, headers={**headers, "If-Match": "1"}).status_code == 409
    result = client.get("/v1/nutrition-summary?start_date=2026-09-14", headers=headers)
    assert result.json()["totals"]["energy_kcal"] == 150
    assert client.delete(url, headers={**headers, "If-Match": "2"}).status_code == 200
    assert client.get(url, headers=headers).status_code == 404


def test_profile_and_error_shapes(client):
    headers = {"Authorization": "Bearer alice", "If-Match": "0"}
    assert client.patch("/v1/profile", json=PROFILE, headers=headers).status_code == 200
    response = client.patch("/v1/profile", json={"timezone": "unknown"}, headers={**headers, "If-Match": "1"})
    assert response.status_code == 422
    assert set(response.json()) == {"code", "message", "request_id", "details"}
    assert client.get("/v1/nutrition-summary?start_date=bad", headers=headers).status_code == 422


@pytest.mark.parametrize("locator", [[12, "2026-09-15", "bad"], [None, "2026-09-15", "bad"],
                                    {"a": 1, "b": 2, "c": 3}, ["x"], ["x", 12, []]])
def test_malformed_locators_are_validation_errors(locator):
    from imhungry.services import encode
    client = TestClient(create_app(NutritionService(MemoryRepository()), verifier=lambda t: t),
                        raise_server_exceptions=False)
    response = client.get("/v1/food-log/" + encode(locator), headers={"Authorization": "Bearer alice"})
    assert response.status_code == 422
    assert response.json()["code"] == "validation"


def test_cognito_verifies_signature_and_claims():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=private.public_key()))
    issuer = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_example"
    verifier = CognitoVerifier(issuer, "client", jwks_client=jwks)
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {"iss": issuer, "sub": str(uuid4()), "client_id": "client", "token_use": "access", "iat": now, "exp": now + 600}
    assert verifier(jwt.encode(claims, private, algorithm="RS256")) == claims["sub"]
    for patch in [{"iss": "https://attacker"}, {"client_id": "other"}, {"token_use": "id"}, {"exp": now - 100}, {"sub": ""}]:
        with pytest.raises(AppError):
            verifier(jwt.encode({**claims, **patch}, private, algorithm="RS256"))
    with pytest.raises(AppError):
        verifier(jwt.encode(claims, other, algorithm="RS256"))
    with pytest.raises(AppError):
        verifier(jwt.encode({k: v for k, v in claims.items() if k != "exp"}, private, algorithm="RS256"))
