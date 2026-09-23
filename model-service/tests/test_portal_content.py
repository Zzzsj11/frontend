"""Presentation transforms only: synthetic payloads, no media/model network requests."""

from types import SimpleNamespace

from gateway.portal_content import content_view, task_content


def test_content_whitelist_and_text_protocols():
    payload = {
        "api_key": "secret",
        "headers": {"Authorization": "secret"},
        "messages": [
            {"role": "system", "content": "System prompt"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "User prompt"},
                    {"type": "image_url", "image_url": {"url": "https://media.test/ref.png"}},
                ],
            },
        ],
    }
    content = content_view(payload)
    assert [x["text"] for x in content["texts"]] == ["System prompt", "User prompt"]
    assert content["media"][0]["kind"] == "image"
    assert "secret" not in str(content)
    for result in [
        {"choices": [{"message": {"role": "assistant", "content": "answer"}}]},
        {"content": [{"type": "text", "text": "answer"}]},
        {"output": [{"content": [{"type": "output_text", "text": "answer"}]}]},
    ]:
        view = task_content(SimpleNamespace(kind="chat", payload=payload, result=result))
        assert view["result_content"]["texts"] == [{"role": "assistant", "text": "answer"}]


def test_video_image_reference_formats_and_archived_results():
    cases = [
        {
            "content": [
                {"type": "text", "text": "prompt"},
                {"type": "image_url", "image_url": {"url": "https://media.test/ref.png"}, "role": "first_frame"},
                {"type": "video_url", "video_url": {"url": "https://media.test/ref.mp4"}},
            ]
        },
        {
            "input": {
                "prompt": "prompt",
                "media": [
                    {"type": "reference_image", "url": "https://media.test/ref.png"},
                    {"type": "reference_audio", "url": "https://media.test/ref.mp3"},
                ],
            }
        },
        {
            "prompt": "prompt",
            "image_with_roles": [{"url": "https://media.test/ref.png", "role": "first_frame"}],
            "video_with_roles": [{"url": "https://media.test/ref.mp4"}],
        },
    ]
    for payload in cases:
        view = content_view(payload)
        assert view["texts"][0]["text"] == "prompt"
        assert len(view["media"]) == 2
    for kind in ["image", "video"]:
        view = task_content(
            SimpleNamespace(
                kind=kind,
                payload={"prompt": "prompt"},
                result={
                    "native": {"secret": "hidden"},
                    "media": [{"url": "https://media.test/output", "thumbnail_url": "https://media.test/thumb.png"}],
                },
            )
        )
        assert view["result_content"]["media"][0]["kind"] == kind
        assert "hidden" not in str(view)
    bad = content_view({"images": ["javascript:alert(1)", "https://user:password@host.test/a", "data:text/html,unsafe"]})
    assert bad["media"] == []
