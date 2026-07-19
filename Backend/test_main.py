from fastapi.testclient import TestClient
import main
from main import app

client = TestClient(app)


def test_generate_question_requires_auth():
    response = client.get("/generateQuestion", params={"chapter": "Differentiation"})
    assert response.status_code == 401


def test_generate_quiz_requires_auth():
    response = client.get("/generateQuiz", params={"chap": "Integrals"})
    assert response.status_code == 401


def test_calc_section_requires_auth():
    response = client.get("/CalcSection", params={"c": "Calculator-Section"})
    assert response.status_code == 401


def test_get_history_requires_auth():
    response = client.get("/getHistory")
    assert response.status_code == 401


def test_get_stats_requires_auth():
    response = client.get("/getStats", params={"chapter": "Differentiation"})
    assert response.status_code == 401


def test_cors_blocks_foreign_origin():
    response = client.options(
        "/login",
        headers={
            "Origin": "https://some-random-other-site.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    allowed = response.headers.get("access-control-allow-origin")
    assert allowed != "https://some-random-other-site.com"
    assert allowed != "*"


def test_cors_allows_configured_origin():
    response = client.options(
        "/login",
        headers={
            "Origin": main.ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") == main.ALLOWED_ORIGIN


def test_login_rate_limit_kicks_in():
    last_status = None
    for _ in range(10):
        response = client.post(
            "/login",
            json={"email": "nobody@example.com", "password": "wrongpassword"},
        )
        last_status = response.status_code
        if last_status == 429:
            break
    assert last_status == 429


def test_register_rate_limit_kicks_in():
    payload = {
        "name": "Rate Limit Test",
        "email": "ratelimit.test@example.com",
        "password": "testpassword123",
    }
    last_status = None
    for _ in range(10):
        response = client.post("/register", json=payload)
        last_status = response.status_code
        if last_status == 429:
            break
    assert last_status == 429
