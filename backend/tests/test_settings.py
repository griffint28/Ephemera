import pytest
from pydantic import ValidationError

from ephemera.settings import Settings

BASE = {"DB_NAME": "n", "DB_USER": "u", "DB_PASSWORD": "p@ss:w/rd"}


def _env(monkeypatch, values):
    for key in ("DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "ORBITAL_REFRESH_HOURS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize("missing", ["DB_NAME", "DB_USER", "DB_PASSWORD"])
def test_credentials_have_no_defaults(monkeypatch, missing):
    _env(monkeypatch, {k: v for k, v in BASE.items() if k != missing})
    with pytest.raises(ValidationError):
        Settings()


def test_url_escapes_password_and_defaults_host(monkeypatch):
    _env(monkeypatch, BASE)
    s = Settings()
    assert s.database_url.password == "p@ss:w/rd"
    assert s.database_url.host == "localhost" and s.database_url.port == 3306
    assert "p@ss" not in repr(s)  # the secret is masked


def test_refresh_interval_cannot_go_below_two_hours(monkeypatch):
    _env(monkeypatch, {**BASE, "ORBITAL_REFRESH_HOURS": "1.5"})
    with pytest.raises(ValidationError):
        Settings()
    _env(monkeypatch, {**BASE, "ORBITAL_REFRESH_HOURS": "2"})
    assert Settings().orbital_refresh_hours == 2
