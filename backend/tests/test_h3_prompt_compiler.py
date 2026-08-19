from app.h3_prompt_compiler import REFERENCE_SECTIONS, compile_h3_prompt, detect_h3_mode
from app.schemas import VideoGenerationCreate


def test_h3_mode_detection_and_reference_compilation():
    payload = VideoGenerationCreate(
        prompt="故宫女性参考视频跳舞",
        duration=10,
        image_urls=["https://tos.test/woman.png"],
        video_urls=["https://tos.test/dance.mp4"],
        audio_urls=["https://tos.test/bgm.wav"],
        h3_audio_usage="reuse",
    )
    assert detect_h3_mode(payload) == "reference"
    compiled = compile_h3_prompt(payload)
    assert all(section in compiled.prompt for section in REFERENCE_SECTIONS)
    assert compiled.reference_bindings["Picture 1"]["type"] == "image"
    assert compiled.reference_bindings["Video 1"]["type"] == "video"
    assert compiled.reference_bindings["Audio 1"]["usage"] == "reuse"
    assert "fully_copy" in compiled.prompt


def test_h3_compiler_preserves_expert_prompt_verbatim():
    prompt = "\n\n".join(f"{section}\nvalue" for section in REFERENCE_SECTIONS)
    payload = VideoGenerationCreate(prompt=prompt, image_urls=["a.png", "b.png"])
    compiled = compile_h3_prompt(payload)
    assert compiled.prompt == prompt
    assert compiled.source_prompt == prompt


def test_h3_base_modes():
    text = VideoGenerationCreate(prompt="雨中的城市")
    first = VideoGenerationCreate(prompt="人物转身", image_urls=["first.png"])
    assert detect_h3_mode(text) == "text"
    assert detect_h3_mode(first) == "first_frame"
    assert compile_h3_prompt(text).prompt.startswith("integrated_multimodal_description:")
