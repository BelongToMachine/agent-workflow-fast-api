from app.core.csrf import (
    generate_csrf_token,
    is_allowed_origin,
    validate_csrf_token,
)


def test_csrf_tokens_compare_in_constant_time() -> None:
    token = generate_csrf_token()

    assert validate_csrf_token(token, token) is True
    assert validate_csrf_token(token, token + "x") is False
    assert validate_csrf_token(token, "中文") is False


def test_origin_validation_requires_an_exact_non_null_origin() -> None:
    allowed = ["https://copilot.asianodeatlas.com", "http://localhost:5173"]

    assert is_allowed_origin("https://copilot.asianodeatlas.com", allowed) is True
    assert is_allowed_origin("https://evil.example", allowed) is False
    assert is_allowed_origin("null", allowed) is False
    assert is_allowed_origin(None, allowed) is False
