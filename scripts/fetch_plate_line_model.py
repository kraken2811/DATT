"""Install the pinned optional plate OCR model; does not install dependencies."""
import hashlib
from pathlib import Path
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / 'models/ocr/en_PP-OCRv4_rec_mobile.onnx'
SHA256 = 'e8770c967605983d1570cdf5352041dfb68fa0c21664f49f47b155abd3e0e318'
URL = 'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile.onnx'


def main():
    if DESTINATION.is_file() and hashlib.sha256(DESTINATION.read_bytes()).hexdigest() == SHA256:
        print('plate_line_model=VERIFIED')
        return
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=DESTINATION.parent, suffix='.download', delete=False) as target:
            temporary = Path(target.name)
            size = 0
            with urllib.request.urlopen(URL, timeout=60) as response:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 16 * 1024 * 1024:
                        raise ValueError('Unexpected model download size')
                    target.write(chunk)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != SHA256:
            raise ValueError('Model download checksum mismatch; existing model was retained')
        temporary.replace(DESTINATION)
        print('plate_line_model=VERIFIED')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
