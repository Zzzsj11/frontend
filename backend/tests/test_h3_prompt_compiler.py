import pytest
from fastapi import HTTPException

from app.h3_prompt_compiler import REFERENCE_SECTIONS, compile_h3_prompt, detect_h3_mode
from app.main import validate_h3_mode_inputs
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
    payload = VideoGenerationCreate(prompt=prompt, image_urls=["a.png", "b.png"], generate_audio=True)
    compiled = compile_h3_prompt(payload)
    assert compiled.prompt == prompt
    assert compiled.source_prompt == prompt


def test_h3_compiler_only_rewrites_audio_sections_for_silent_expert_prompt():
    prompt = "\n\n".join(f"{section}\nvalue" for section in REFERENCE_SECTIONS)
    compiled = compile_h3_prompt(VideoGenerationCreate(prompt=prompt, image_urls=["a.png", "b.png"], generate_audio=False))

    assert compiled.source_prompt == prompt
    assert "subject_definitions:\nvalue" in compiled.prompt
    assert "overall_soundscape:\nN/A" in compiled.prompt
    assert compiled.prompt.endswith("non_diegetic_music:\nN/A")


def test_h3_base_modes():
    text = VideoGenerationCreate(prompt="雨中的城市")
    first = VideoGenerationCreate(prompt="人物转身", image_urls=["first.png"])
    assert detect_h3_mode(text) == "text"
    assert detect_h3_mode(first) == "first_frame"
    assert compile_h3_prompt(text).prompt.startswith("integrated_multimodal_description:")
    assert "generate a silent video with no audio track" in compile_h3_prompt(text).prompt


def test_h3_compiler_keeps_audio_only_when_enabled():
    enabled = VideoGenerationCreate(prompt="雨中的城市", generate_audio=True)
    disabled = VideoGenerationCreate(prompt="雨中的城市", generate_audio=False)

    assert "physically plausible ambience" in compile_h3_prompt(enabled).prompt
    assert "non_diegetic_music: Follow the creative direction" in compile_h3_prompt(enabled).prompt
    assert "no audio track" in compile_h3_prompt(disabled).prompt
    assert "non_diegetic_music: N/A" in compile_h3_prompt(disabled).prompt


def test_h3_first_last_prompt_has_exact_alignment_instruction():
    payload = VideoGenerationCreate(
        prompt="人物从站立连续转为舞蹈收势",
        duration=8,
        image_urls=["first.png", "last.png"],
        h3_mode="first_last",
    )
    compiled = compile_h3_prompt(payload)
    assert compiled.mode == "first_last"
    assert compiled.prompt.startswith("How the reference pictures align with the target video")
    assert "8.00-second mark" in compiled.prompt
    assert "Picture 1" in compiled.prompt and "Picture 2" in compiled.prompt


def test_h3_product_mode_validation_excludes_tail_only_and_checks_inputs():
    validate_h3_mode_inputs(VideoGenerationCreate(prompt="x", h3_mode="first_last", image_urls=["first.png", "last.png"]))
    with pytest.raises(HTTPException, match="首尾帧"):
        validate_h3_mode_inputs(VideoGenerationCreate(prompt="x", h3_mode="first_last", image_urls=["first.png"]))
    with pytest.raises(ValueError):
        VideoGenerationCreate(prompt="x", h3_mode="reference", image_urls=[f"{index}.png" for index in range(7)])
