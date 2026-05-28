from __future__ import annotations

from track_fraude.vision.carry import CarryProfile


def test_net_carry_theft_enter_empty_exit_with_object():
    profile = CarryProfile(
        carry_at_enter={
            "hands_empty": True,
            "hand_objects": 0,
            "carry_score": 0.1,
            "bag": False,
        },
        carry_at_exit={
            "hands_empty": False,
            "hand_objects": 1,
            "carry_score": 0.7,
            "bag": False,
        },
        confidence=0.8,
        source="test",
    )
    delta = profile.carry_delta()
    assert delta["enter_empty"] is True
    assert delta["exit_empty"] is False
    assert delta["net_objects"] == 1
    assert delta["positive"] is True
    assert profile.has_net_carry_theft()


def test_net_carry_no_theft_enter_and_exit_empty():
    profile = CarryProfile(
        carry_at_enter={
            "hands_empty": True,
            "hand_objects": 0,
            "carry_score": 0.1,
            "bag": False,
        },
        carry_at_exit={
            "hands_empty": True,
            "hand_objects": 0,
            "carry_score": 0.12,
            "bag": False,
        },
        confidence=0.8,
        source="test",
    )
    delta = profile.carry_delta()
    assert delta["positive"] is False
    assert not profile.has_net_carry_theft()


def test_net_carry_own_bag_baseline_no_increase():
    profile = CarryProfile(
        carry_at_enter={
            "hands_empty": False,
            "hand_objects": 1,
            "carry_score": 0.5,
            "bag": True,
        },
        carry_at_exit={
            "hands_empty": False,
            "hand_objects": 1,
            "carry_score": 0.52,
            "bag": True,
        },
        confidence=0.8,
        source="test",
    )
    delta = profile.carry_delta()
    assert delta["net_objects"] == 0
    assert delta["positive"] is False


def test_yolo_suppresses_bbox_false_positive():
    """BBox indica carga na saída, mas YOLO vê 0 objetos nos dois instantes."""
    profile = CarryProfile(
        carry_at_enter={
            "hands_empty": True,
            "hand_objects_bbox": 0,
            "hand_objects_yolo": 0,
            "hand_objects": 0,
            "carry_score": 0.1,
            "bag": False,
        },
        carry_at_exit={
            "hands_empty": True,
            "hand_objects_bbox": 1,
            "hand_objects_yolo": 0,
            "hand_objects": 1,
            "carry_score": 0.55,
            "bag": False,
        },
        confidence=0.8,
        source="bbox+yolo",
    )
    delta = profile.carry_delta()
    assert delta["yolo_available"] is True
    assert delta["net_objects_bbox"] == 1
    assert delta["net_objects_yolo"] == 0
    assert delta["positive"] is False
    assert not profile.has_net_carry_theft()


def test_yolo_confirms_carry_theft():
    profile = CarryProfile(
        carry_at_enter={
            "hands_empty": True,
            "hand_objects_bbox": 0,
            "hand_objects_yolo": 0,
            "hand_objects": 0,
            "carry_score": 0.1,
            "bag": False,
        },
        carry_at_exit={
            "hands_empty": False,
            "hand_objects_bbox": 0,
            "hand_objects_yolo": 1,
            "hand_objects": 1,
            "carry_score": 0.2,
            "bag": False,
            "yolo_labels": ["bottle"],
        },
        confidence=0.75,
        source="bbox+yolo",
    )
    delta = profile.carry_delta()
    assert delta["net_objects_yolo"] == 1
    assert delta["positive"] is True
    assert profile.has_net_carry_theft()
