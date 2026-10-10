"""Private supervised backend runner, keeps CV unchanged and allows API-only mode."""
import argparse
import os
import re
import sys
import subprocess
import threading
import time

from .config import runtime_dir


class SafeOutput:
    def __init__(self, stream):
        self.stream = stream
        self.secrets = [v for k, v in os.environ.items() if v and
                        any(part in k.upper() for part in ('PASSWORD', 'TOKEN', 'SECRET', 'KEY', 'DATABASE_URL', 'STORAGE_OPTIONS'))]
        try:
            from sqlalchemy.engine import make_url
            from urllib.parse import quote
            password = make_url(os.getenv('DATT_DATABASE_URL', 'sqlite://')).password
            if password:
                self.secrets.extend([password, quote(password, safe='')])
        except Exception:
            pass

    def write(self, value):
        for secret in sorted(self.secrets, key=len, reverse=True):
            value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'\b(?:postgres(?:ql)?(?:\+\w+)?|https?)://[^\s\"\']+', '[URL]', value)
        return self.stream.write(value)

    def flush(self):
        self.stream.flush()

    def isatty(self):
        return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--token', required=True)
    p.add_argument('--mode', choices=['api', 'cpu', 'gpu'], required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--ai-port', type=int, required=True)
    args = p.parse_args()
    sys.stdout, sys.stderr = SafeOutput(sys.stdout), SafeOutput(sys.stderr)
    try:
        from src.agent.api.auth import validate_auth_configuration
        validate_auth_configuration()

        # Frontend compilation is deployment presentation work. It must never
        # prevent the AI/CV/API runtime from starting. Colab always has the
        # tracked React bundle as a safe fallback; runtime builds are best-effort.
        runtime_react_dist = None
        try:
            from src.ui.runtime_frontend import prepare_runtime_frontend
            runtime_react_dist = prepare_runtime_frontend()
        except Exception as exc:
            print('runtime_frontend=FALLBACK; build_error=' + type(exc).__name__, flush=True)

        import src.ui.web_server as web_server
        if runtime_react_dist is not None:
            try:
                from src.ui.runtime_frontend import configure_runtime_frontend
                configure_runtime_frontend(web_server, runtime_react_dist)
            except Exception as exc:
                print('runtime_frontend=FALLBACK; configure_error=' + type(exc).__name__, flush=True)
                runtime_react_dist = None

        app = web_server.app
        revision = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True,
                                  timeout=10).stdout.strip() or 'unavailable'
        from src.agent.config import agent_config
        app.state.backend_url = f'http://127.0.0.1:{args.ai_port}'

        @app.get('/healthz')
        def health():
            return {'status': 'ok', 'mode': args.mode, 'instance': args.token,
                    'commit': revision, 'application_module': 'src.ui.web_server',
                    'agent_llm_provider': agent_config.llm_provider,
                    'runtime_frontend': bool(runtime_react_dist)}

        @app.get('/startup-health')
        def startup_health():
            # Observation only: do not import/initialize any business singleton.
            threads = {t.name for t in threading.enumerate() if t.is_alive()}
            return {
                'notification_worker': 'RUNNING' if 'NotificationEmailWorker' in threads else 'STOPPED',
                'persistence_worker': 'RUNNING' if 'DatabasePersistenceWorker' in threads else 'STOPPED',
            }

        marker = runtime_dir() / (args.token + '.stop')
        if args.mode == 'api':
            import uvicorn
            server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, access_log=False))
            def shutdown():
                server.should_exit = True
            run = server.run
        else:
            if args.mode == 'cpu':
                import config
                config.DEVICE = 'cpu'
            # Preserve the canonical src/main.py preflight and RuntimeManager flow.
            import _thread
            from src.main import main as run_main
            sys.argv = ['src/main.py', '--host', '127.0.0.1', '--port', str(args.port), '--ai-port', str(args.ai_port)]
            shutdown = _thread.interrupt_main
            run = run_main

        def watch():
            while not marker.exists():
                time.sleep(.2)
            shutdown()
        threading.Thread(target=watch, daemon=True).start()
        run()
    except Exception as exc:
        print('backend_error=' + type(exc).__name__, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
