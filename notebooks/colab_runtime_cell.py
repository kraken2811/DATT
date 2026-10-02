# CELL 1 — Provision the supported CUDA stack, then test the GPU
import os, sys, json, subprocess, socket
from pathlib import Path

ROOT = Path('/content/DATT')
startup = None
runtime = None
print('python=' + sys.version.split()[0])
expected = {'torch': '2.11.0+cu126', 'torchvision': '0.26.0+cu126', 'torchaudio': '2.11.0+cu126'}
version_code = "import importlib.metadata as m,json; names=('torch','torchvision','torchaudio'); print(json.dumps({n:m.version(n) for n in names if m.packages_distributions().get(n)}))"
versions = subprocess.run([sys.executable, '-c', version_code], capture_output=True, text=True, timeout=90)
if versions.returncode:
    raise RuntimeError('Khong doc duoc phien ban Torch trong runtime.')
if json.loads(versions.stdout) != expected:
    # Do not replace native libraries underneath a running kernel/service.
    if any(n in sys.modules for n in ('torch', 'torchvision', 'torchaudio', 'onnxruntime')):
        raise RuntimeError('Chon Runtime > Restart session, sau do chay lai Cell 1 de cai Torch cu126. Khong Delete runtime.')
    for port in (8000, 8501):
        with socket.socket() as sock:
            sock.settimeout(1)
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError('Dung dich vu DATT bang CLI truoc khi doi Torch: port ' + str(port))
    if subprocess.run(['nvidia-smi', '-L'], capture_output=True, timeout=30).returncode:
        raise RuntimeError('Chon GPU T4 trong Runtime > Change runtime type.')
    print('Dang cai Torch CUDA 12.6 tu download.pytorch.org; co the mat vai phut.', flush=True)
    log_path = Path('/content/datt-torch-install.log')
    with log_path.open('w') as log:
        result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
            '--only-binary=:all:', '--index-url', 'https://download.pytorch.org/whl/cu126',
            *[n + '==' + v for n, v in expected.items()]], stdout=log, stderr=subprocess.STDOUT, timeout=1200)
    if result.returncode:
        raise RuntimeError('Cai Torch cu126 that bai; xem /content/datt-torch-install.log, sau do chay lai Cell 1.')
probe_code = "import torch,torchvision,torchaudio,json; x=torch.arange(4,device='cuda'); torch.cuda.synchronize(); print(json.dumps(dict(gpu=torch.cuda.get_device_name(0),cuda=torch.version.cuda,available=torch.cuda.is_available(),torch=torch.__version__,torchvision=torchvision.__version__,torchaudio=torchaudio.__version__,tensor_ok=(x.sum().item()==6))))"
probe = subprocess.run([sys.executable, '-c', probe_code], capture_output=True, text=True, timeout=90)
if probe.returncode:
    Path('/content/datt-gpu-probe.log').write_text(probe.stderr)
    raise RuntimeError('GPU smoke test FAIL; xem /content/datt-gpu-probe.log.')
info = json.loads(probe.stdout)
for key in ('gpu', 'torch', 'cuda', 'available', 'tensor_ok'):
    print(str(key) + '=' + str(info[key]))
if not info['available'] or info['cuda'] != '12.6' or not info['tensor_ok'] or any(info[n] != v for n, v in expected.items()):
    raise RuntimeError('Can bo Torch cu126 dong bo va GPU tensor test PASS de tiep tuc.')
runtime = dict(runtime='colab', gpu=info['gpu'], cuda=info['cuda'], runtime_pid=os.getpid())
print('cell1=PASS')
