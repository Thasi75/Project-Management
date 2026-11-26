import argparse
import json
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import uvicorn

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=18765)
parser.add_argument('--no-browser', action='store_true')
args = parser.parse_args()
base = 'http://127.0.0.1:' + str(args.port)


def open_when_ready():
    for _ in range(120):
        try:
            with urllib.request.urlopen(base + '/api/health', timeout=1) as response:
                if json.load(response).get('app_id') == 'delivery-workbench':
                    webbrowser.open(base)
                    return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)


if not args.no_browser:
    threading.Thread(target=open_when_ready, daemon=True).start()
uvicorn.run('backend.main:app', host='127.0.0.1', port=args.port)
