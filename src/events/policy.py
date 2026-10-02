"""Per-camera threshold episodes; no CV, database or cross-camera aggregation."""
from dataclasses import dataclass
from uuid import uuid4

PEOPLE_THRESHOLD = 40
PEOPLE_DURATION_THRESHOLD = 180.0
VEHICLE_THRESHOLD = 40
MEANINGFUL_EVENTS = frozenset({
    'FACE_WATCHLIST_MATCH', 'CROWD_THRESHOLD',
    'VEHICLE_WATCHLIST_MATCH', 'VEHICLE_CONGESTION',
})


@dataclass
class Episode:
    started: float
    wall_started: float
    token: str
    active: bool = False


class ThresholdEpisodes:
    def __init__(self):
        self.crowds = {}
        self.vehicles = {}

    def people(self, camera_id, count, now, wall, location=None):
        key = (camera_id, location)
        if count <= PEOPLE_THRESHOLD:
            self.crowds.pop(key, None)
            return None
        if key not in self.crowds:
            self.crowds[key] = Episode(now, wall, uuid4().hex)
        episode = self.crowds[key]
        elapsed = now - episode.started
        if episode.active or elapsed < PEOPLE_DURATION_THRESHOLD:
            return None
        episode.active = True
        return dict(event_type='CROWD_THRESHOLD', people_count=int(count), threshold=40,
                    duration_seconds=elapsed, location=location, episode=episode.token,
                    timestamp=episode.wall_started + PEOPLE_DURATION_THRESHOLD)

    def congestion(self, camera_id, count, now, wall, location=None):
        key = (camera_id, location)
        if count <= VEHICLE_THRESHOLD:
            self.vehicles.pop(key, None)
            return None
        if key in self.vehicles:
            return None
        self.vehicles[key] = Episode(now, wall, uuid4().hex, True)
        return dict(event_type='VEHICLE_CONGESTION', vehicle_count=int(count), threshold=40,
                    location=location, episode=self.vehicles[key].token, timestamp=wall)

    def reset(self):
        self.crowds.clear()
        self.vehicles.clear()
