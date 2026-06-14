from __future__ import annotations

from types import SimpleNamespace

from app.gwy.skills.position_recommendation_skills import (
    extract_position_recommendation_criteria,
    position_passes_hard_filters,
)


def test_avoid_conditions_are_loaded_from_profile() -> None:
    profile = SimpleNamespace(
        major="law",
        education="undergraduate",
        degree="bachelor",
        avoid_conditions=["night shift", "field work"],
    )

    criteria = extract_position_recommendation_criteria("recommend positions", profile)

    assert criteria.major == "law"
    assert criteria.avoid_conditions == ["night shift", "field work"]


def test_avoid_conditions_block_matching_positions() -> None:
    position = SimpleNamespace(
        remarks="this role includes night shift work",
        raw_data={},
    )
    criteria = extract_position_recommendation_criteria(
        "recommend positions",
        SimpleNamespace(
            major="law",
            education="undergraduate",
            degree="bachelor",
            avoid_conditions=["night shift"],
        ),
    )

    passed, reasons, risks = position_passes_hard_filters(position, criteria)

    assert passed is False
    assert reasons == ["鍛戒腑閬垮厤鏉′欢"]
    assert risks
