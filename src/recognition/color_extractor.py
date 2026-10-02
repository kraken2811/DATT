"""Clothing Color Extraction for Person Bounding Boxes.

Extracts dominant clothing color from the upper torso region of a person bounding box
using HSV color space analysis.

Key robustness measures:
- Bounding box clamping to frame dimensions
- Head region exclusion (top 15%)
- Central torso region extraction (15% to 65% height, center 70% width)
- Exclusion of background edges
- Basic colors: 'red', 'blue', 'green', 'yellow', 'black', 'white'
"""

from dataclasses import dataclass
import logging
from typing import Sequence

import cv2
import numpy as np

logger = logging.getLogger("datt.color_extractor")

# Standard basic colors
COLOR_NAMES = ("red", "blue", "green", "yellow", "black", "white")


@dataclass(frozen=True)
class ColorAnalysisResult:
    """Result of clothing color analysis."""
    dominant_color: str
    confidence: float  # Percentage of valid pixels matching dominant color
    color_distribution: dict[str, float]


class ClothingColorExtractor:
    """Extracts dominant clothing color from person crops."""

    def __init__(self, min_valid_pixels: int = 40) -> None:
        self.min_valid_pixels = min_valid_pixels

    def extract_torso_crop(
        self,
        frame: np.ndarray,
        bbox: Sequence[float | int],
    ) -> np.ndarray | None:
        """Extract central upper-body torso region from a full frame and person bbox.

        Args:
            frame: Full BGR frame (H, W, 3)
            bbox: [x1, y1, x2, y2]

        Returns:
            np.ndarray | None: Cropped torso region, or None if invalid.
        """
        if frame is None or len(bbox) < 4:
            return None

        fh, fw = frame.shape[:2]
        x1, y1, x2, y2 = [int(v) for v in bbox[:4]]

        # Clamp to frame boundaries
        x1 = max(0, min(x1, fw - 1))
        y1 = max(0, min(y1, fh - 1))
        x2 = max(0, min(x2, fw))
        y2 = max(0, min(y2, fh))

        bw = x2 - x1
        bh = y2 - y1

        if bw < 10 or bh < 20:
            return None

        # Torso boundaries:
        # Exclude head (top 15%), take up to 65% of person height
        torso_y1 = y1 + int(bh * 0.15)
        torso_y2 = y1 + int(bh * 0.65)

        # Take central 70% of width to exclude background at the lateral edges
        margin_x = int(bw * 0.15)
        torso_x1 = x1 + margin_x
        torso_x2 = x2 - margin_x

        if torso_x2 <= torso_x1 or torso_y2 <= torso_y1:
            return None

        crop = frame[torso_y1:torso_y2, torso_x1:torso_x2]
        if crop.size == 0 or crop.shape[0] < 5 or crop.shape[1] < 5:
            return None

        return crop

    def analyze_crop(self, crop: np.ndarray) -> ColorAnalysisResult | None:
        """Classify dominant color of a cropped torso image in HSV space."""
        if crop is None or crop.size == 0:
            return None

        h, w = crop.shape[:2]
        total_pixels = h * w
        if total_pixels < self.min_valid_pixels:
            return None

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        H = hsv[:, :, 0]
        S = hsv[:, :, 1]
        V = hsv[:, :, 2]

        # Masks for achromatic colors
        black_mask = V < 60
        white_mask = (S < 50) & (V >= 160)

        # Chromatic pixels
        chromatic_mask = ~black_mask & ~white_mask & (S >= 40)

        # Color classifications for chromatic pixels
        # Red wraps around 0 and 180 in OpenCV HSV
        red_mask = chromatic_mask & ((H <= 10) | (H >= 165))
        yellow_mask = chromatic_mask & ((H > 10) & (H <= 35))
        green_mask = chromatic_mask & ((H > 35) & (H <= 85))
        blue_mask = chromatic_mask & ((H > 85) & (H < 165))

        counts = {
            "black": int(np.count_nonzero(black_mask)),
            "white": int(np.count_nonzero(white_mask)),
            "red": int(np.count_nonzero(red_mask)),
            "yellow": int(np.count_nonzero(yellow_mask)),
            "green": int(np.count_nonzero(green_mask)),
            "blue": int(np.count_nonzero(blue_mask)),
        }

        classified_pixels = sum(counts.values())
        if classified_pixels < self.min_valid_pixels:
            return None

        distribution = {
            c: round(count / classified_pixels, 3)
            for c, count in counts.items()
        }

        dominant_color = max(distribution, key=distribution.get)
        confidence = distribution[dominant_color]

        return ColorAnalysisResult(
            dominant_color=dominant_color,
            confidence=confidence,
            color_distribution=distribution,
        )

    def extract_clothing_color(
        self,
        frame: np.ndarray,
        bbox: Sequence[float | int],
    ) -> ColorAnalysisResult | None:
        """Convenience method combining crop and color analysis."""
        crop = self.extract_torso_crop(frame, bbox)
        if crop is None:
            return None
        return self.analyze_crop(crop)


# Convenience singleton instance
clothing_color_extractor = ClothingColorExtractor()

VEHICLE_COLOR_NAMES = (
    "white",
    "black",
    "gray/silver",
    "red",
    "blue",
    "green",
    "yellow",
    "other/unknown",
)


def extract_vehicle_color(crop: np.ndarray | None) -> str:
    """Backward-compatible label API using the unchanged vehicle HSV masks."""
    label, _ = analyze_vehicle_color(crop)
    return 'other/unknown' if label == 'unknown' else label


def analyze_vehicle_color(crop: np.ndarray | None) -> tuple[str, float]:
    """Classify basic vehicle color from a cropped vehicle image using HSV.

    Returns the label and winning classified-pixel fraction, not a calibrated
    model probability. The existing masks and gray/silver ambiguity are retained.

    Categories:
    - 'white'
    - 'black'
    - 'gray/silver'
    - 'red'
    - 'blue'
    - 'green'
    - 'yellow'
    - 'other/unknown'
    """
    if crop is None or not isinstance(crop, np.ndarray) or crop.size == 0:
        return "unknown", 0.0

    h, w = crop.shape[:2]
    if h < 10 or w < 10:
        return "unknown", 0.0

    # Focus on the vehicle body (exclude windshield/sky at top and wheels/asphalt at bottom)
    y1 = int(h * 0.20)
    y2 = int(h * 0.80)
    x1 = int(w * 0.15)
    x2 = int(w * 0.85)

    if (y2 - y1) < 5 or (x2 - x1) < 5:
        body = crop
    else:
        body = crop[y1:y2, x1:x2]

    if body.size == 0:
        return "unknown", 0.0

    hsv = cv2.cvtColor(body, cv2.COLOR_BGR2HSV)
    H = hsv[:, :, 0]
    S = hsv[:, :, 1]
    V = hsv[:, :, 2]

    # Achromatic masks
    black_mask = V < 55
    white_mask = (S < 45) & (V >= 170)
    gray_mask = (S < 45) & (V >= 55) & (V < 170)

    # Chromatic mask
    chromatic_mask = ~black_mask & ~white_mask & ~gray_mask & (S >= 40) & (V >= 50)

    # Color classifications in OpenCV HSV (H in [0, 180])
    red_mask = chromatic_mask & ((H <= 10) | (H >= 165))
    yellow_mask = chromatic_mask & ((H > 10) & (H <= 35))
    green_mask = chromatic_mask & ((H > 35) & (H <= 85))
    blue_mask = chromatic_mask & ((H > 85) & (H < 165))

    counts = {
        "black": int(np.count_nonzero(black_mask)),
        "white": int(np.count_nonzero(white_mask)),
        "gray/silver": int(np.count_nonzero(gray_mask)),
        "red": int(np.count_nonzero(red_mask)),
        "yellow": int(np.count_nonzero(yellow_mask)),
        "green": int(np.count_nonzero(green_mask)),
        "blue": int(np.count_nonzero(blue_mask)),
    }

    classified_pixels = sum(counts.values())
    if classified_pixels < 25:
        return "unknown", 0.0

    dominant_color, dominant_count = max(counts.items(), key=lambda item: item[1])
    if dominant_count / classified_pixels >= 0.18:
        return dominant_color, float(dominant_count / classified_pixels)

    return "unknown", 0.0
