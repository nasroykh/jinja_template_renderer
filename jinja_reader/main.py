"""CLI entry point for jinja_reader."""

from __future__ import annotations

import argparse
import http.server
import json
import socketserver
import sys
import threading
import time
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .mock_data import generate_mock_data

# ---------------------------------------------------------------------------
# Live-reload support
# ---------------------------------------------------------------------------

_last_render_time: list[float] = [0.0]

_LIVE_RELOAD_SCRIPT = (
    '<script>(function(){'
    'var t=0;'
    'function poll(){'
    "fetch('/__lr?_='+Date.now())"
    '.then(function(r){return r.text()})'
    '.then(function(v){'
    'if(t&&parseFloat(v)!==t){location.reload()}'
    't=parseFloat(v)'
    '}).catch(function(){})'
    '}'
    'setInterval(poll,300);poll();'
    '})();</script>'
)


class _LiveReloadHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler that adds a ``/__lr`` polling endpoint for live reload."""

    def do_GET(self) -> None:
        if self.path.startswith("/__lr"):
            body = str(_last_render_time[0]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, fmt: str, *args: object) -> None:
        # Suppress per-request logs in watch mode
        pass


class _ReuseAddrServer(socketserver.TCPServer):
    allow_reuse_address = True


def _make_handler(root: Path, live_reload: bool) -> type:
    """Return an HTTP handler class bound to *root* as its document root."""
    root_str = str(root)
    base = _LiveReloadHandler if live_reload else http.server.SimpleHTTPRequestHandler

    class Handler(base):  # type: ignore[valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=root_str, **kwargs)  # type: ignore[call-arg]

        def log_message(self, fmt: str, *args: object) -> None:
            pass

    return Handler


def _run_server(port: int, root: Path, live_reload: bool = False) -> None:
    """Serve *root* on 127.0.0.1:*port*."""
    root = root.resolve()
    if not root.is_dir():
        print(f"Error: Serve root not found: {root}", file=sys.stderr)
        return
    handler = _make_handler(root, live_reload)
    with _ReuseAddrServer(("127.0.0.1", port), handler) as httpd:
        httpd.serve_forever()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _inject_live_reload(html: str) -> str:
    """Insert live-reload script just before the last </body> tag."""
    idx = html.lower().rfind("</body>")
    if idx == -1:
        return html + _LIVE_RELOAD_SCRIPT
    return html[:idx] + _LIVE_RELOAD_SCRIPT + "\n" + html[idx:]


def _render(template_path: Path, output_path: Path, inject_live_reload: bool = False) -> bool:
    """
    Render *template_path* with generated mock data and write to *output_path*.
    Uses a filesystem loader so {% include %} / {% extends %} work.
    Returns True on success.
    """
    try:
        _, context = generate_mock_data(template_path)
        env = Environment(
            loader=FileSystemLoader(str(template_path.parent)),
            keep_trailing_newline=True,
        )
        template = env.get_template(template_path.name)
        rendered = template.render(**context)
        if inject_live_reload:
            rendered = _inject_live_reload(rendered)
        output_path.write_text(rendered, encoding="utf-8")
        _last_render_time[0] = time.time()
        return True
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return False


def _watch_loop(
    template_path: Path,
    output_path: Path,
    inject_live_reload: bool = False,
    interval: float = 0.5,
) -> None:
    """Poll *template_path* for mtime changes and re-render on change."""
    last_mtime = 0.0
    print(
        f"Watching {template_path.name} → {output_path.name}  (Ctrl+C to stop)",
        file=sys.stderr,
    )
    while True:
        try:
            mtime = template_path.stat().st_mtime
            if mtime != last_mtime:
                last_mtime = mtime
                if _render(template_path, output_path, inject_live_reload):
                    print(f"[{time.strftime('%H:%M:%S')}] Rendered", file=sys.stderr)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"Watch error: {exc}", file=sys.stderr)
        time.sleep(interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_url_path(output_path: Path, serve_root: Path) -> str:
    try:
        rel = output_path.relative_to(serve_root)
    except ValueError:
        rel = Path(output_path.name)
    return str(rel).replace("\\", "/")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="jinja-reader",
        description="Render a Jinja template with mock data.",
    )
    parser.add_argument(
        "template",
        type=Path,
        nargs="?",
        default=None,
        help="Path to Jinja template (default: template.jinja)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output file (default: index.html next to the template)",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Print mock context as JSON instead of rendering",
    )
    parser.add_argument(
        "--list-vars",
        action="store_true",
        help="Print extracted variable paths and exit",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Re-render whenever the template file changes",
    )
    parser.add_argument(
        "--serve",
        type=int,
        nargs="?",
        const=3000,
        metavar="PORT",
        help="Serve the output directory on localhost (default port 3000)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Document root for --serve (default: output file directory)",
    )
    args = parser.parse_args()

    template_path = (args.template or Path("template.jinja")).resolve()
    if not template_path.exists():
        print(f"Error: Template not found: {template_path}", file=sys.stderr)
        return 1

    output_path = (args.output or template_path.parent / "index.html").resolve()
    serve_root = (args.root or output_path.parent).resolve()

    # --list-vars: extract and print, no rendering
    if args.list_vars:
        from .mock_data import generate_mock_data as _gmd
        extracted, _ = _gmd(template_path)
        print("Variable paths:")
        for p in sorted(extracted.variable_paths):
            print(f"  {p}")
        print("\nIterable paths:")
        for p in sorted(extracted.iterable_paths):
            print(f"  {p}")
        if extracted.loop_vars:
            print("\nLoop variable mappings:")
            for ip, lv in sorted(extracted.loop_vars.items()):
                print(f"  {ip} → {lv}")
        return 0

    # --json-only: emit mock context as JSON
    if args.json_only:
        extracted, context = generate_mock_data(template_path)

        def _to_plain(obj: object) -> object:
            if hasattr(obj, "to_dict"):
                return _to_plain(obj.to_dict())  # type: ignore[union-attr]
            if isinstance(obj, dict):
                return {k: _to_plain(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_to_plain(v) for v in obj]
            return obj

        print(json.dumps(_to_plain(context), indent=2, ensure_ascii=False))
        return 0

    # --watch (with optional --serve)
    if args.watch:
        live = args.serve is not None
        if live:
            _render(template_path, output_path, inject_live_reload=True)
            url = _build_url_path(output_path, serve_root)
            print(f"Serving at http://127.0.0.1:{args.serve}/{url}", file=sys.stderr)
            threading.Thread(
                target=_run_server,
                args=(args.serve, serve_root, True),
                daemon=True,
            ).start()
        _watch_loop(template_path, output_path, inject_live_reload=live)
        return 0

    # --serve only (single render then serve)
    if args.serve is not None:
        if not _render(template_path, output_path):
            return 1
        url = _build_url_path(output_path, serve_root)
        print(f"Serving at http://127.0.0.1:{args.serve}/{url}", file=sys.stderr)
        _run_server(args.serve, serve_root)
        return 0

    # Default: single render
    if not _render(template_path, output_path):
        return 1
    if args.output:
        print(f"Rendered to {output_path}")
    else:
        print(output_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
