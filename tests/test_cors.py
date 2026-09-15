from fastapi.testclient import TestClient
from imhungry.api import create_app
from test_services import service
from test_repository import repo


def test_unexpected_errors_have_request_id_and_approved_cors(service, monkeypatch):
    def fail(*args):
        raise RuntimeError("private database details")
    monkeypatch.setattr(service, "get", fail)
    client = TestClient(create_app(service, verifier=lambda t: t, cors_origins=["https://approved.example"]),
                        raise_server_exceptions=False)
    for origin in ["https://approved.example", "https://untrusted.example"]:
        response = client.get("/v1/profile", headers={"Authorization": "Bearer alice", "Origin": origin})
        assert response.status_code == 503
        assert response.headers["X-Request-ID"] == response.json()["request_id"]
        assert "private" not in response.text
        assert response.headers.get("Access-Control-Allow-Origin") == (origin if "approved" in origin else None)


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
