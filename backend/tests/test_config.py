from app import config


def test_shared_provider_configuration_is_kept_as_one_group(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_CHANNEL", "")
    monkeypatch.setenv("LLM_API_KEY", "stale-token")
    monkeypatch.setenv("LLM_BASE_URL", "https://wrong.example/v1")
    monkeypatch.setenv("LLM_MODEL", "wrong-model")

    base_url, api_key, model = config._resolve_llm_settings("shared-token", "https://shared.example/v1", "shared-model")

    assert api_key == "shared-token"
    assert base_url == "https://shared.example/v1"
    assert model == "shared-model"


def test_overseas_text_channel_uses_its_own_key_without_changing_media(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_CHANNEL", "yseeai")
    monkeypatch.setenv("YSEEAI_LLM_MODEL", "gpt-6.1-sol")
    monkeypatch.setattr(config, "_read_provider_value", lambda name: "overseas-key" if name == "YSEEAI_LLM_API_KEY" else "")

    assert config._resolve_llm_settings("domestic-key", "https://ai-aigc.fzyinghe.com/v1", "gpt-5.6-sol") == (
        "https://ai-aigc.yseeai.com/v1",
        "overseas-key",
        "gpt-6.1-sol",
    )


def test_toapis_text_channel_uses_separate_key_or_existing_toapis_key(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_CHANNEL", "toapis")
    monkeypatch.setenv("TOAPIS_LLM_MODEL", "gpt-6.1-sol")
    monkeypatch.delenv("TOAPIS_LLM_BASE_URL", raising=False)
    values = {"TOAPIS_LLM_API_KEY": "text-key", "TOAPIS_API_KEY": "video-key"}
    monkeypatch.setattr(config, "_read_provider_value", lambda name: values.get(name, ""))

    assert config._resolve_llm_settings("domestic-key", "https://domestic.example/v1", "domestic-model") == (
        "https://toapis.com/v1",
        "text-key",
        "gpt-6.1-sol",
    )
    values.pop("TOAPIS_LLM_API_KEY")
    assert config._resolve_llm_settings("domestic-key", "https://domestic.example/v1", "domestic-model")[1] == "video-key"


def test_material_export_downloads_allow_twenty_parallel_files() -> None:
    assert config.settings.export_download_concurrency == 20
    assert config.settings.export_upload_part_size_mb == 5
    assert config.settings.tos_request_timeout_seconds == 180
    assert config.settings.tos_socket_timeout_seconds == 180
    assert config.settings.tos_max_retry_count == 5


def test_media_generation_defaults_support_large_batches() -> None:
    assert config.settings.daily_image_limit == 1000
    assert config.settings.daily_video_limit == 1000
    assert config.settings.image_generation_concurrency == 200
    assert config.settings.video_generation_concurrency == 200
    assert config.settings.provider_generation_worker_concurrency == 200
    assert config.settings.image_result_processing_concurrency == 40
    assert config.settings.video_result_processing_concurrency == 20
