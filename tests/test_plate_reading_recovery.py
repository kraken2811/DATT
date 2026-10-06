import threading
from unittest.mock import Mock
import numpy as np
import pytest
from src.ocr.plate_line_recognizer import PlateLineRecognizer
from src.ocr.plate_reader import is_valid_plate_format


def recognizer(parts, regions=None):
    obj = object.__new__(PlateLineRecognizer)
    obj.read_line = Mock(side_effect=parts)
    if regions is None:
        regions = [((3, 4, 53, 44), np.ones((40, 50, 3), dtype=np.uint8))]
    obj.plate_regions = Mock(return_value=regions)
    return obj


def test_two_rows_produce_observed_text_and_native_region():
    result = recognizer([('24-X1', .92), ('124.42', .98)]).read_plate(None, None, is_valid_plate_format)
    assert result.text == '24X112442'
    assert result.raw_text == '24-X1\n124.42'
    assert result.confidence == .92
    assert result.bbox == (3, 4, 53, 44)


@pytest.mark.parametrize('parts', [
    [('', .99), ('12442', .99)], [('24X1', .99), ('', .99)],
    [('24X1', .79), ('12442', .99)], [('24X1', .99), ('124', .99)],
    [('2LX1', .99), ('12442', .99)], [('24X1', .99), ('512442', .99)],
])
def test_weak_missing_or_invalid_rows_are_not_repaired_from_a_plate_pattern(parts):
    assert recognizer(parts).read_plate(None, None, is_valid_plate_format) is None


def test_disagreeing_crops_are_not_selected_by_confidence_alone():
    image = np.zeros((20, 100, 3), dtype=np.uint8)
    obj = recognizer([('29K10425', .91), ('29K10225', .99)],
                     [((0, 0, 100, 20), image), ((1, 0, 100, 20), image)])
    assert obj.read_plate(None, None, is_valid_plate_format) is None


def test_pixel_preparation_preserves_bgr_and_aspect_ratio_with_zero_padding():
    image = np.zeros((24, 48, 3), dtype=np.uint8)
    image[:, :, 0] = 255
    tensor = PlateLineRecognizer.prepare(image)
    assert tensor.shape == (1, 3, 48, 320)
    assert np.all(tensor[0, 0, :, :96] == 1)
    assert np.all(tensor[0, 1:, :, :96] == -1)
    assert np.all(tensor[:, :, :, 96:] == 0)


def test_ctc_decoding_keeps_repeated_characters_separated_by_blank():
    obj = object.__new__(PlateLineRecognizer)
    obj.characters = ['', '1', '2']
    obj._lock = threading.Lock()
    obj.input_name = 'x'
    obj.session = Mock()
    probabilities = np.eye(3, dtype=np.float32)[[1, 1, 0, 1, 2]][None]
    obj.session.run.return_value = [probabilities]
    assert obj.read_line(np.ones((20, 50, 3), dtype=np.uint8)) == ('112', 1.0)
    probabilities[:] = np.nan
    assert obj.read_line(np.ones((20, 50, 3), dtype=np.uint8)) == ('', 0.0)


def test_model_checksum_rejected_before_session_creation(tmp_path):
    path = tmp_path/'bad.onnx'
    path.write_bytes(b'not-the-approved-model')
    with pytest.raises(ValueError, match='checksum'):
        PlateLineRecognizer(path)


def test_refinement_never_escapes_detector_roi():
    image = np.zeros((100, 150, 3), dtype=np.uint8)
    image[25:55, 60:100] = 240
    regions = PlateLineRecognizer.plate_regions(image, (40, 20, 105, 60))
    assert len(regions) == 2
    for (x1,y1,x2,y2), crop in regions:
        assert 40 <= x1 < x2 <= 105 and 20 <= y1 < y2 <= 60
        assert crop.shape[:2] == (y2-y1, x2-x1)
