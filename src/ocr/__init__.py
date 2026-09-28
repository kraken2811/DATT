"""License Plate Localization, Recognition (OCR), and Tracking Module."""

from src.ocr.plate_reader import (
    LicensePlateCandidate,
    LicensePlateReader,
    PlateCandidate,
    clean_plate_text,
    is_valid_plate_format,
    plate_reader,
)
from src.ocr.plate_tracker import (
    PlateTrackState,
    VehiclePlateManager,
    vehicle_plate_manager,
)

__all__ = [
    "PlateCandidate",
    "LicensePlateCandidate",
    "clean_plate_text",
    "is_valid_plate_format",
    "LicensePlateReader",
    "plate_reader",
    "PlateTrackState",
    "VehiclePlateManager",
    "vehicle_plate_manager",
]
