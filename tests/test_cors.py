from fastapi.testclient import TestClient
from imhungry.api import create_app
from test_services import service
from test_repository import repo


def test_browser_preflight_and_auth_errors(service):
    origin = "https://main.example.amplifyapp.com"
    client = TestClient(create_app(service, cors_origins=[origin]))
    response = client.options("/v1/profile", headers={"Origin": origin,
        "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "authorization,content-type,if-match,idempotency-key"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin
    response = client.get("/v1/profile", headers={"Origin": origin})
    assert response.status_code == 401
    assert response.headers["Access-Control-Allow-Origin"] == origin
    response = client.options("/v1/profile", headers={"Origin": "https://untrusted.example",
        "Access-Control-Request-Method": "PATCH"})
    assert response.status_code == 400
    assert "Access-Control-Allow-Origin" not in response.headers
