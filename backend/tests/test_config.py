import importlib

from app import config


def reload_with(monkeypatch, **env):
    for k in ("REDIS_URL", "REDIS_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return importlib.reload(config)


def test_redis_password_is_injected_and_escaped(monkeypatch):
    c = reload_with(monkeypatch, REDIS_URL="redis://redis:6379/0", REDIS_PASSWORD="p@ss/w:rd")
    assert c.REDIS_URL == "redis://:p%40ss%2Fw%3Ard@redis:6379/0"


def test_redis_url_credentials_win_over_password(monkeypatch):
    c = reload_with(monkeypatch, REDIS_URL="redis://:own@redis:6379/0", REDIS_PASSWORD="other")
    assert c.REDIS_URL == "redis://:own@redis:6379/0"


def test_redis_without_password_unchanged(monkeypatch):
    assert reload_with(monkeypatch, REDIS_URL="redis://redis:6379/0").REDIS_URL == "redis://redis:6379/0"
    importlib.reload(config)
