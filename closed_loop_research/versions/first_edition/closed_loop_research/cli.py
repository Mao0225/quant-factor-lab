"""Public research commands. Training never invokes V or T evaluation."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

from .protocol import Protocol
from .storage import read_json, atomic_json


def parser():
    p = argparse.ArgumentParser(description="Independent closed-loop research prototype")
    sub = p.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import-legacy", help="copy old 500-code data into an independent prototype snapshot")
    imp.add_argument("--source", type=Path, default=Path("single_factor/data/selected_500_liquid_processed/panel.parquet"))
    imp.add_argument("--destination", type=Path, required=True)
    imp.add_argument("--sessions", type=int, default=120)
    imp.add_argument("--seed", type=int, default=7)
    train = sub.add_parser("train")
    train.add_argument("--data", type=Path, required=True, help="directory containing protocol.json and snapshot/")
    train.add_argument("--run", type=Path, required=True)
    train.add_argument("--batches-this-call", type=int)
    for name in ["resume", "select", "test", "report", "status", "serve"]:
        cmd = sub.add_parser(name)
        cmd.add_argument("--run", type=Path, required=True)
        if name == "resume": cmd.add_argument("--batches-this-call", type=int)
        if name == "serve": cmd.add_argument("--port", type=int, default=8765)
    suite = sub.add_parser("suite")
    suite.add_argument("--data", type=Path, required=True)
    suite.add_argument("--output", type=Path, required=True)
    suite.add_argument("--seeds", type=int, nargs="+", default=[7, 19])
    suite.add_argument("--groups", nargs="+", choices=list("ABCDE"), default=list("ABCDE"))
    suite.add_argument("--final-test", action="store_true")
    derive = sub.add_parser("derive-protocol")
    derive.add_argument("--source", type=Path, required=True)
    derive.add_argument("--output", type=Path, required=True)
    derive.add_argument("--beta", type=float)
    derive.add_argument("--reward", choices=["trade_delta", "single_ic", "combo_ic", "absolute_trade"])
    derive.add_argument("--search-mode", choices=["adaptive", "fixed"])
    derive.add_argument("--wall-seconds", type=float)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "import-legacy":
        from .legacy import import_legacy
        result = import_legacy(args.source, args.destination, sessions=args.sessions, seed=args.seed)
    elif args.command in {"train", "resume"}:
        from .runner import run_experiment
        if args.command == "train":
            p = Protocol.from_dict(read_json(args.data / "protocol.json"))
            snapshot = args.data / "snapshot"
        else:
            p = Protocol.from_dict(read_json(args.run / "protocol.json"))
            snapshot = read_json(args.run / "experiment.json")["snapshot_path"]
        if args.batches_this_call is not None and args.batches_this_call < 1:
            raise ValueError("batches-this-call must be positive")
        state = run_experiment(p, snapshot, args.run, max_batches_this_call=args.batches_this_call)
        result = {k: state[k] for k in ["batch", "phase", "pool_version", "pool", "ppo_updates", "budget", "stop_reason"]}
    elif args.command in {"select", "test"}:
        from .selection import select_model, test_model
        result = select_model(args.run) if args.command == "select" else test_model(args.run)
    elif args.command == "report":
        from .report import build_report
        result = {"report": str(build_report(args.run).resolve())}
    elif args.command == "status":
        result = read_json(args.run / "status.json")
    elif args.command == "serve":
        from .report import build_report
        report = build_report(args.run)
        # Serve only the generated report: no directory listing, checkpoints or data paths.
        class ReportHandler(SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path.split("?")[0] not in {"/", "/report.html"}:
                    self.send_error(404)
                    return
                data = report.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def do_HEAD(self):
                self.send_error(405)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), ReportHandler)
        print(f"Research workbench: http://127.0.0.1:{args.port}/report.html", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    elif args.command == "suite":
        from .comparison import run_suite
        p = Protocol.from_dict(read_json(args.data / "protocol.json"))
        full = run_suite(p, args.data / "snapshot", args.output, args.seeds, args.groups, args.final_test)
        result = dict(suite_id=full["suite_id"], summary=full["summary"])
    else:
        if args.output.exists():
            raise FileExistsError("derive requires a new protocol path")
        raw = read_json(args.source)
        for name, key in [("beta", "beta"), ("reward", "reward_mode"), ("search_mode", "search_mode"), ("wall_seconds", "wall_seconds")]:
            if getattr(args, name) is not None:
                raw[key] = getattr(args, name)
        p = Protocol.from_dict(raw)
        atomic_json(args.output, p.to_dict())
        result = dict(path=str(args.output), protocol_digest=p.digest)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0
