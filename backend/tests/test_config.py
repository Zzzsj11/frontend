from app import config


def test_shared_provider_configuration_is_kept_as_one_group(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "stale-token")
    monkeypatch.setenv("LLM_BASE_URL", "https://wrong.example/v1")
    monkeypatch.setenv("LLM_MODEL", "wrong-model")

    base_url, api_key, model = config._resolve_llm_settings("shared-token", "https://shared.example/v1", "shared-model")

    assert api_key == "shared-token"
    assert base_url == "https://shared.example/v1"
    assert model == "shared-model"
