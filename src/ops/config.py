import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_configuration():
    # Explicit environment wins. No interpolation/command execution in .env.
    path = ROOT / '.env'
    if path.is_file():
        from dotenv import load_dotenv
        load_dotenv(path, override=False, interpolate=False)
    # userdata requires the notebook kernel; shell children inherit its env.
    # Importing google.colab in a plain subprocess is not sufficient.
    if environment() == 'colab':
        try:
            from IPython import get_ipython
            in_kernel = get_ipython() is not None
        except ImportError:
            in_kernel = False
        if in_kernel:
            from scripts.colab_bootstrap import load_secrets
            load_secrets()


def environment():
    import importlib.util
    try:
        colab = importlib.util.find_spec('google.colab') is not None
    except ModuleNotFoundError:
        colab = False
    return 'colab' if colab and os.path.isdir('/content') else 'local'


def runtime_dir():
    path = Path(os.getenv('DATT_RUNTIME_DIR', ROOT / '.datt-runtime')).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path
