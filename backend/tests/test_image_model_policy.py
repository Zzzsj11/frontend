import pytest
from fastapi import HTTPException

from app.all_in_one_catalog import rows
from app.image_model_policy import image_ratio, validate_image_selection

NANO = {
    "ratios": ["16:9", "9:16", "4:3", "1:1", "3:2", "2:3", "3:4"],
    "resolutions": ["1K", "2K", "4K"],
    "referenceImage": {"min": 0, "max": 14},
}

SEEDREAM = next(row["capabilities"] for row in rows({}) if row["code"] == "seedream-5.0-pro-all-in-one")


def test_nano_accepts_portrait_ratio_and_references():
    assert image_ratio("1024x1536") == "2:3"
    validate_image_selection(
        "nano-banana-2.1-all-in-one",
        NANO,
        size="1024x1536",
        resolution="1K",
        purpose="digital_human",
        images=["https://example.test/ref.jpg"],
    )


def test_seedream_supports_portraits_wide_and_reference_limit():
    validate_image_selection("seedream-5.0-pro-all-in-one", SEEDREAM, size="16:9", resolution="1.5K", purpose="digital_human", images=["https://example.test/face.jpg"])
    for changes in ({"resolution": "4K"}, {"images": ["https://example.test/ref.jpg"] * 11}):
        with pytest.raises(HTTPException) as error:
            validate_image_selection("seedream-5.0-pro-all-in-one", SEEDREAM, **{"size": "1:1", "resolution": "2K", **changes})
        assert error.value.status_code == 422
