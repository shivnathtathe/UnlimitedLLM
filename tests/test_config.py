from app.config import Settings


def test_upstream_environment_variables_take_precedence(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "legacy-key")
    monkeypatch.setenv("NVIDIA_BASE_URL", "https://legacy.example/v1")
    monkeypatch.setenv("NVIDIA_DEFAULT_MODEL", "legacy-model")
    monkeypatch.setenv("NVIDIA_MODELS", "legacy-model")
    monkeypatch.setenv("UPSTREAM_API_KEY", "upstream-key")
    monkeypatch.setenv("UPSTREAM_BASE_URL", "https://upstream.example/v1")
    monkeypatch.setenv("UPSTREAM_DEFAULT_MODEL", "upstream-model")
    monkeypatch.setenv("UPSTREAM_MODELS", "upstream-model,other-model")

    settings = Settings()

    assert settings.upstream_api_key == "upstream-key"
    assert settings.upstream_base_url == "https://upstream.example/v1"
    assert settings.default_model == "upstream-model"
    assert settings.known_models == ("upstream-model", "other-model")


def test_legacy_nvidia_environment_variables_remain_supported(monkeypatch):
    for name in (
        "UPSTREAM_API_KEY",
        "UPSTREAM_BASE_URL",
        "UPSTREAM_DEFAULT_MODEL",
        "UPSTREAM_MODELS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "legacy-key")
    monkeypatch.setenv("NVIDIA_BASE_URL", "https://legacy.example/v1")
    monkeypatch.setenv("NVIDIA_DEFAULT_MODEL", "legacy-model")
    monkeypatch.setenv("NVIDIA_MODELS", "legacy-model")

    settings = Settings()

    assert settings.upstream_api_key == "legacy-key"
    assert settings.upstream_base_url == "https://legacy.example/v1"
    assert settings.default_model == "legacy-model"
    assert settings.known_models == ("legacy-model",)
