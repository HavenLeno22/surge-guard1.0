"""The site topology store - operator-drawn links between camera zones."""

from __future__ import annotations

from pathlib import Path

import pytest
from surgeguard_ai.contracts import FlowLinkConfig

from app.cameras.topology_store import TopologyStore, TopologyStoreError

ENTRANCE_TO_QUEUE = FlowLinkConfig(
    from_camera_id="cam-01",
    from_zone_id="entrance",
    to_camera_id="CAM-02",
    to_zone_id="queue-a",
)


def test_a_missing_file_is_an_empty_topology(tmp_path: Path) -> None:
    store = TopologyStore(tmp_path / "topology.json")
    assert store.links == ()
    assert store.load_error is None
    assert not (tmp_path / "topology.json").exists()


def test_links_round_trip_with_normalised_camera_ids(tmp_path: Path) -> None:
    path = tmp_path / "topology.json"
    TopologyStore(path).save([ENTRANCE_TO_QUEUE])

    (link,) = TopologyStore(path).links
    assert link.to_camera_id == "cam-02"
    assert link.link_id == "cam-01:entrance->cam-02:queue-a"
    assert link.crosses_cameras


def test_duplicate_links_are_stored_once(tmp_path: Path) -> None:
    saved = TopologyStore(tmp_path / "topology.json").save([ENTRANCE_TO_QUEUE, ENTRANCE_TO_QUEUE])
    assert len(saved) == 1


def test_a_zone_cannot_feed_itself(tmp_path: Path) -> None:
    store = TopologyStore(tmp_path / "topology.json")
    with pytest.raises(TopologyStoreError, match="cannot feed itself"):
        store.save(
            [
                FlowLinkConfig(
                    from_camera_id="cam-01",
                    from_zone_id="queue-a",
                    to_camera_id="cam-01",
                    to_zone_id="queue-a",
                )
            ]
        )


def test_an_unreadable_file_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "topology.json"
    path.write_text("[]", encoding="utf-8")

    store = TopologyStore(path)

    assert store.load_error is not None
    with pytest.raises(TopologyStoreError, match="could not be read"):
        store.save([ENTRANCE_TO_QUEUE])
    assert path.read_text(encoding="utf-8") == "[]"
