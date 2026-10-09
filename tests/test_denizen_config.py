from app.config import Settings


def test_denizen_connection_environment(monkeypatch):
    for name in ("TEXT_MODEL_BASE_URL", "TEXT_MODEL_API_KEY", "TEXT_MODEL_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BLU_API_BASE", "https://inference.example.test/v1")
    monkeypatch.setenv("BLU_API_KEY", "test-denizen-secret")
    monkeypatch.setenv("BLU_MODEL", "test-qwen-deployment")
    settings = Settings(_env_file=None)
    assert settings.text_model_base_url == "https://inference.example.test/v1"
    assert settings.text_model_api_key == "test-denizen-secret"
    assert settings.text_model_name == "test-qwen-deployment"
    assert "test-denizen-secret" not in repr(settings)


def test_growthos_connection_takes_precedence(monkeypatch):
    monkeypatch.setenv("BLU_API_BASE", "https://other.example.test/v1")
    monkeypatch.setenv("BLU_MODEL", "other-model")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://selected.example.test/v1")
    monkeypatch.setenv("TEXT_MODEL_NAME", "selected-model")
    settings = Settings(_env_file=None)
    assert settings.text_model_base_url == "https://selected.example.test/v1"
    assert settings.text_model_name == "selected-model"
