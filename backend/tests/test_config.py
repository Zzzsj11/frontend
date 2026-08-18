from app import config


def test_shared_provider_configuration_is_kept_as_one_group(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "stale-token")
    monkeypatch.setenv("LLM_BASE_URL", "https://wrong.example/v1")
    monkeypatch.setenv("LLM_MODEL", "wrong-model")

    base_url, api_key, model = config._resolve_llm_settings("shared-token", "https://shared.example/v1", "shared-model")

    assert api_key == "shared-token"
    assert base_url == "https://shared.example/v1"
    assert model == "shared-model"


def test_material_export_downloads_allow_twenty_parallel_files() -> None:
    assert config.settings.export_download_concurrency == 20


def test_media_generation_defaults_support_large_batches() -> None:
    assert config.settings.daily_image_limit == 1000
    assert config.settings.daily_video_limit == 1000
    assert config.settings.image_generation_concurrency == 200
    assert config.settings.video_generation_concurrency == 200
    assert config.settings.provider_generation_worker_concurrency == 200
    assert config.settings.image_result_processing_concurrency == 40
    assert config.settings.video_result_processing_concurrency == 20
