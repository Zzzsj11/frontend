"""Versioned H3 prompt compiler derived from the h3-prompt-writing rules."""

from __future__ import annotations

from dataclasses import dataclass

from .schemas import VideoGenerationCreate

COMPILER_NAME = "h3-prompt-writing"
COMPILER_VERSION = "1.2.0"
BASE_SECTIONS = ("integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:")
REFERENCE_SECTIONS = ("subject_definitions:", "summary:", "retention_analysis:", "detailed_description:", "overall_soundscape:", "non_diegetic_music:")


@dataclass(frozen=True)
class H3PromptCompilation:
    prompt: str
    source_prompt: str
    mode: str
    compiler: str
    version: str
    reference_bindings: dict[str, dict[str, str]]
    warnings: tuple[str, ...] = ()


def detect_h3_mode(payload: VideoGenerationCreate) -> str:
    if payload.h3_mode != "auto":
        return payload.h3_mode
    if payload.video_urls or payload.audio_urls or len(payload.image_urls) > 1:
        return "reference"
    return "first_frame" if payload.image_urls else "text"


def _already_structured(prompt: str, sections: tuple[str, ...]) -> bool:
    positions = [prompt.find(section) for section in sections]
    return all(position >= 0 for position in positions) and positions == sorted(positions)


def _silence_structured_prompt(prompt: str) -> str:
    soundscape = prompt.find("overall_soundscape:")
    music = prompt.find("non_diegetic_music:", soundscape)
    return (
        (
            prompt[:soundscape]
            + "overall_soundscape:\nN/A — generate a silent video with no audio track, ambience, dialogue, sound effects, or music.\n\n"
            + "non_diegetic_music:\nN/A"
        )
        if soundscape >= 0 and music >= 0
        else prompt
    )


def _bindings(payload: VideoGenerationCreate) -> dict[str, dict[str, str]]:
    bindings: dict[str, dict[str, str]] = {}
    for index, url in enumerate(payload.image_urls, 1):
        bindings[f"Picture {index}"] = {"type": "image", "url": url}
    for index, url in enumerate(payload.video_urls, 1):
        bindings[f"Video {index}"] = {"type": "video", "url": url}
    for index, url in enumerate(payload.audio_urls, 1):
        bindings[f"Audio {index}"] = {"type": "audio", "url": url, "usage": payload.h3_audio_usage}
    return bindings


def compile_h3_prompt(payload: VideoGenerationCreate) -> H3PromptCompilation:
    """Compile a safe default structure and preserve valid expert H3 prompts verbatim."""
    source = payload.prompt.strip()
    mode = detect_h3_mode(payload)
    bindings = _bindings(payload)
    sections = REFERENCE_SECTIONS if mode == "reference" else BASE_SECTIONS
    if _already_structured(source, sections):
        compiled = source if payload.generate_audio else _silence_structured_prompt(source)
        return H3PromptCompilation(compiled, source, mode, COMPILER_NAME, COMPILER_VERSION, bindings)

    soundscape = (
        "Preserve physically plausible ambience and synchronized action sounds; do not add dialogue unless explicitly requested."
        if payload.generate_audio
        else "N/A — generate a silent video with no audio track, ambience, dialogue, sound effects, or music."
    )
    music = "Follow the creative direction; use N/A when no audience-only music is requested." if payload.generate_audio else "N/A"

    if mode != "reference":
        instruction = ""
        picture_note = ""
        if mode == "first_frame":
            instruction = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
            picture_note = " Begin exactly from <Picture 1> and preserve its identity, composition, and scene continuity."
        elif mode == "first_last":
            instruction = (
                "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with "
                f"the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the {payload.duration:.2f}-second mark of the target video.\n\n"
            )
            picture_note = " Begin exactly from Picture 1, describe a continuous visible transition, and converge exactly to Picture 2 at the end."
        compiled = (
            f"{instruction}integrated_multimodal_description: [Shot 1] Create a {payload.duration}-second {payload.ratio} target video.{picture_note} Creative direction: {source}\n\n"
            f"overall_soundscape: {soundscape}\n\n"
            f"non_diegetic_music: {music}"
        )
        return H3PromptCompilation(compiled, source, mode, COMPILER_NAME, COMPILER_VERSION, bindings)

    definitions: list[str] = []
    retention: list[str] = []
    for index in range(1, len(payload.image_urls) + 1):
        definitions.append(f"<Subject {index}> is the visible identity, subject, scene, composition, and style supplied by <Picture {index}>.")
        retention.append(f"<Subject {index}> (appears where required): fully_preserved - retain the defining visible attributes from <Picture {index}> consistently.")
    offset = len(payload.image_urls)
    for index in range(1, len(payload.video_urls) + 1):
        subject = offset + index
        definitions.append(f"<Subject {subject}> is the motion, action timing, camera rhythm, and temporal structure supplied by <Video {index}>.")
        retention.append(
            f"<Subject {subject}> (appears where required): fully_preserved - transfer the requested motion and timing from <Video {index}> without replacing the target visual identity."
        )
    audio_marker = {"reuse": "fully_copy", "reference": "reference", "generated": "weak_reference", "mute": "weak_reference"}[payload.h3_audio_usage]
    for index in range(1, len(payload.audio_urls) + 1):
        role = "complete audience-only background score" if payload.h3_audio_usage == "reuse" else "audio rhythm, music, timbre, or sound reference"
        definitions.append(f"<Audio {index}> is the supplied {role}.")
        retention.append(f"<Audio {index}>: {audio_marker} - apply the requested audio usage without inventing an unrelated role.")
    task_types = ["reference generation"]
    if payload.audio_urls:
        task_types.append("audio reuse" if payload.h3_audio_usage == "reuse" else "audio reference")
    labels = ", ".join(f"<{label}>" for label in bindings) or "the supplied references"
    music = (
        (
            "Reuse <Audio 1> as the complete audience-only score, trimming only at the target-video boundary."
            if payload.audio_urls and payload.h3_audio_usage == "reuse"
            else "Reference the supplied audio labels according to retention_analysis; use N/A when no music is requested."
        )
        if payload.generate_audio
        else "N/A"
    )
    compiled = (
        "subject_definitions:\n" + "\n".join(definitions) + "\n\n"
        f"summary:\n[{' + '.join(task_types)}] Create a {payload.duration}-second {payload.ratio} target video using {labels} according to the creative direction.\n\n"
        "retention_analysis:\n" + "\n".join(retention) + "\n\n"
        f"detailed_description:\nThe target video follows this creative direction in playback order: {source}\n"
        "Keep labels consistent, preserve identity and continuity, and avoid blur, identity drift, duplicate subjects, malformed anatomy, unintended cuts, text, logos, and watermarks.\n\n"
        f"overall_soundscape:\n{soundscape}\n\n"
        f"non_diegetic_music:\n{music}"
    )
    warnings = () if definitions else ("Ref2VA prompt has no bound reference definitions.",)
    return H3PromptCompilation(compiled, source, mode, COMPILER_NAME, COMPILER_VERSION, bindings, warnings)
