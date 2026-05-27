from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from track_fraude.merge.appearance import extract_track_appearances
from track_fraude.merge.matcher import CrossCameraLink, match_entrance_to_checkout
from track_fraude.merge.track_profile import (
    TrackProfile,
    build_track_profiles,
    entered_at_from_timeline,
    group_rows_by_track,
    track_key,
)
from track_fraude_core.db.camera_roles import (
    CAMERA_ROLE_CHECKOUT,
    CAMERA_ROLE_ENTRANCE,
)


def resolve_merge_cameras(config: dict[str, Any]) -> tuple[str, str]:
    entrance_camera: str | None = None
    checkout_camera: str | None = None
    for camera_id, camera in config.get("cameras", {}).items():
        role = str(camera.get("camera_role") or "support")
        if role == CAMERA_ROLE_ENTRANCE:
            entrance_camera = camera_id
        elif role == CAMERA_ROLE_CHECKOUT:
            checkout_camera = camera_id
    if not entrance_camera or not checkout_camera:
        raise ValueError(
            "Re-ID exige uma câmera de entrada e uma de caixa cadastradas no SQLite."
        )
    return entrance_camera, checkout_camera


def _timeline_entered_at(
    timelines: dict[str, Any] | None, *, camera_id: str
) -> dict[int, datetime]:
    if not timelines:
        return {}
    entered: dict[int, datetime] = {}
    for track in timelines.get("tracks", []):
        if track.get("camera_id") != camera_id:
            continue
        entered_at = entered_at_from_timeline(track.get("timeline", []))
        if entered_at is not None:
            entered[int(track["track_id"])] = entered_at
    return entered


def load_video_path_from_manifest(manifest_path: Path | None) -> Path | None:
    if manifest_path is None or not manifest_path.exists():
        return None
    import json

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    video_path = payload.get("video_path")
    return Path(str(video_path)) if video_path else None


def build_persons_document(
    *,
    date: str,
    store_id: str,
    group_code: str,
    entrance_camera: str,
    checkout_camera: str,
    entrance_rows: list[dict[str, Any]],
    checkout_rows: list[dict[str, Any]],
    timelines: dict[str, Any] | None = None,
    entrance_video: Path | None = None,
    checkout_video: Path | None = None,
    max_travel_sec: float = 1800.0,
    min_appearance_score: float = 0.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    entrance_entered = _timeline_entered_at(timelines, camera_id=entrance_camera)
    entrance_appearances = extract_track_appearances(
        entrance_video, group_rows_by_track(entrance_rows, camera_id=entrance_camera)
    ) if entrance_video else {}
    checkout_appearances = extract_track_appearances(
        checkout_video, group_rows_by_track(checkout_rows, camera_id=checkout_camera)
    ) if checkout_video else {}

    entrance_profiles = build_track_profiles(
        entrance_rows,
        camera_id=entrance_camera,
        appearances=entrance_appearances or None,
        entered_at_by_track=entrance_entered or None,
    )
    checkout_profiles = build_track_profiles(
        checkout_rows,
        camera_id=checkout_camera,
        appearances=checkout_appearances or None,
    )

    links = match_entrance_to_checkout(
        entrance_profiles,
        checkout_profiles,
        max_travel_sec=max_travel_sec,
        min_appearance_score=min_appearance_score,
    )

    linked_entrance = {link.entrance_track.track_key for link in links}
    linked_checkout = {link.checkout_track.track_key for link in links}

    persons: list[dict[str, Any]] = []
    cross_links: list[dict[str, Any]] = []
    person_index = 1

    for link in links:
        global_person_id = f"P-{person_index:04d}"
        person_index += 1
        persons.append(
            {
                "global_person_id": global_person_id,
                "tracks": [
                    link.entrance_track.to_dict(),
                    link.checkout_track.to_dict(),
                ],
                "t_first": link.entrance_track.reference_time.isoformat(),
                "t_last": link.checkout_track.t_last.isoformat(),
            }
        )
        link_payload = link.to_dict()
        link_payload["global_person_id"] = global_person_id
        cross_links.append(link_payload)

    for profile in entrance_profiles:
        if profile.track_key in linked_entrance:
            continue
        global_person_id = f"P-{person_index:04d}"
        person_index += 1
        persons.append(
            {
                "global_person_id": global_person_id,
                "tracks": [profile.to_dict()],
                "t_first": profile.reference_time.isoformat(),
                "t_last": profile.t_last.isoformat(),
            }
        )

    for profile in checkout_profiles:
        if profile.track_key in linked_checkout:
            continue
        global_person_id = f"P-{person_index:04d}"
        person_index += 1
        persons.append(
            {
                "global_person_id": global_person_id,
                "tracks": [profile.to_dict()],
                "t_first": profile.t_first.isoformat(),
                "t_last": profile.t_last.isoformat(),
            }
        )

    persons_doc = {
        "date": date,
        "store_id": store_id,
        "group_code": group_code,
        "entrance_camera": entrance_camera,
        "checkout_camera": checkout_camera,
        "person_count": len(persons),
        "cross_camera_link_count": len(cross_links),
        "merge": {
            "max_travel_sec": max_travel_sec,
            "min_appearance_score": min_appearance_score,
            "merged_at": datetime.now(timezone.utc).isoformat(),
        },
        "persons": persons,
    }
    links_doc = {
        "date": date,
        "store_id": store_id,
        "group_code": group_code,
        "link_count": len(cross_links),
        "links": cross_links,
    }
    return persons_doc, links_doc


def apply_persons_to_timelines(
    timelines: dict[str, Any], persons_doc: dict[str, Any]
) -> dict[str, Any]:
    person_by_track_key: dict[str, str] = {}
    for person in persons_doc.get("persons", []):
        global_person_id = str(person["global_person_id"])
        for track in person.get("tracks", []):
            person_by_track_key[str(track["track_key"])] = global_person_id

    payload = dict(timelines)
    enriched_tracks: list[dict[str, Any]] = []
    for track in timelines.get("tracks", []):
        track_copy = dict(track)
        key = str(track_copy.get("track_key") or track_key(
            str(track_copy.get("camera_id")),
            int(track_copy.get("track_id")),
        ))
        track_copy["track_key"] = key
        if key in person_by_track_key:
            track_copy["global_person_id"] = person_by_track_key[key]
        enriched_tracks.append(track_copy)

    payload["tracks"] = enriched_tracks
    payload["persons_ref"] = {
        "person_count": persons_doc.get("person_count", 0),
        "entrance_camera": persons_doc.get("entrance_camera"),
        "checkout_camera": persons_doc.get("checkout_camera"),
    }
    return payload


def person_for_track_key(
    persons_doc: dict[str, Any], track_key_value: str
) -> dict[str, Any] | None:
    for person in persons_doc.get("persons", []):
        for track in person.get("tracks", []):
            if track.get("track_key") == track_key_value:
                return person
    return None


def store_timeline_for_person(
    person: dict[str, Any],
    timelines: dict[str, Any],
    *,
    entrance_camera: str,
) -> list[dict[str, Any]]:
    tracks_by_key = {
        str(track.get("track_key")): track for track in timelines.get("tracks", [])
    }
    for track in person.get("tracks", []):
        if track.get("camera_id") != entrance_camera:
            continue
        track_data = tracks_by_key.get(str(track.get("track_key")))
        if track_data:
            return list(track_data.get("timeline", []))
    return []
