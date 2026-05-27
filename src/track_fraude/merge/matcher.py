from __future__ import annotations

from dataclasses import dataclass

from track_fraude.merge.appearance import compare_appearances
from track_fraude.merge.track_profile import TrackProfile


@dataclass(frozen=True)
class CrossCameraLink:
    entrance_track: TrackProfile
    checkout_track: TrackProfile
    score: float
    temporal_gap_sec: float
    appearance_score: float | None

    def to_dict(self) -> dict:
        payload = {
            "global_person_id": "",
            "entrance_track_key": self.entrance_track.track_key,
            "checkout_track_key": self.checkout_track.track_key,
            "score": round(self.score, 4),
            "temporal_gap_sec": round(self.temporal_gap_sec, 3),
            "method": "temporal+appearance"
            if self.appearance_score is not None
            else "temporal",
        }
        if self.appearance_score is not None:
            payload["appearance_score"] = round(self.appearance_score, 4)
        return payload


def _pair_score(
    entrance: TrackProfile,
    checkout: TrackProfile,
    *,
    max_travel_sec: float,
    min_appearance_score: float,
) -> CrossCameraLink | None:
    gap_sec = (checkout.t_first - entrance.reference_time).total_seconds()
    if gap_sec < 0 or gap_sec > max_travel_sec:
        return None

    appearance_score = None
    if entrance.appearance is not None and checkout.appearance is not None:
        appearance_score = compare_appearances(entrance.appearance, checkout.appearance)
        if appearance_score < min_appearance_score:
            return None
        temporal_component = max(0.0, 1.0 - (gap_sec / max_travel_sec))
        score = 0.6 * appearance_score + 0.4 * temporal_component
    else:
        score = max(0.0, 1.0 - (gap_sec / max_travel_sec))

    return CrossCameraLink(
        entrance_track=entrance,
        checkout_track=checkout,
        score=score,
        temporal_gap_sec=gap_sec,
        appearance_score=appearance_score,
    )


def match_entrance_to_checkout(
    entrance_tracks: list[TrackProfile],
    checkout_tracks: list[TrackProfile],
    *,
    max_travel_sec: float = 1800.0,
    min_appearance_score: float = 0.0,
) -> list[CrossCameraLink]:
    candidates: list[CrossCameraLink] = []
    for entrance in entrance_tracks:
        for checkout in checkout_tracks:
            link = _pair_score(
                entrance,
                checkout,
                max_travel_sec=max_travel_sec,
                min_appearance_score=min_appearance_score,
            )
            if link is not None:
                candidates.append(link)

    candidates.sort(key=lambda item: item.score, reverse=True)
    used_entrance: set[str] = set()
    used_checkout: set[str] = set()
    selected: list[CrossCameraLink] = []

    for link in candidates:
        e_key = link.entrance_track.track_key
        c_key = link.checkout_track.track_key
        if e_key in used_entrance or c_key in used_checkout:
            continue
        used_entrance.add(e_key)
        used_checkout.add(c_key)
        selected.append(link)

    return selected
