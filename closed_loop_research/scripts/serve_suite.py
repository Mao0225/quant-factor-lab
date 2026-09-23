"""Loopback-only viewer exposing generated HTML reports, never data/checkpoints."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from closed_loop_research.storage import read_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    root = args.suite.resolve()
    manifest = read_json(root/'suite_manifest.json')
    allowed = {'/':root/'report.html','/report.html':root/'report.html'}
    for group in manifest['groups']:
        for seed in manifest['seeds']:
            name=f'{group}-seed-{seed}'
            allowed[f'/{name}/report.html']=root/name/'report.html'
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path=allowed.get(urlsplit(self.path).path)
            if path is None or not path.is_file():
                self.send_error(404)
                return
            data=path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    print(f'Multiyear research: http://127.0.0.1:{args.port}/report.html',flush=True)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()
