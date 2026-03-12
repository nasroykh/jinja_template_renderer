"""CLI entry point for jinja_reader."""

from __future__ import annotations

import argparse
import http.server
import json
import shutil
import socketserver
import sys
import threading
import time
from pathlib import Path
from typing import Any

import jinja2.utils as _j2utils
from jinja2 import Environment, FileSystemLoader

from .mock_data import generate_mock_data


class _MockNamespace(_j2utils.Namespace):
    """
    Extends the standard Jinja2 Namespace with a get_formatted() stub.

    Jinja2's Namespace.__getattribute__ only looks inside its internal
    _Namespace__attrs dict (name-mangled), completely bypassing the class
    hierarchy.  We inject get_formatted as a closure into that dict so
    Jinja2 can find and call it.  The closure captures the attrs dict by
    reference, so values set later via {% set ns.x = ... %} are visible.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        attrs: dict[str, Any] = object.__getattribute__(self, "_Namespace__attrs")

        def _fmt(fieldname: str) -> str:
            val = attrs.get(fieldname)
            if val is None:
                return ""
            if isinstance(val, (int, float)):
                return f"{val:,.2f}".replace(",", "\u2009").replace(".", ",")
            return str(val)

        attrs["get_formatted"] = _fmt

# ---------------------------------------------------------------------------
# Package-relative directory layout
# ---------------------------------------------------------------------------

_PKG_DIR = Path(__file__).parent
TEMPLATES_DIR = _PKG_DIR / "templates"
DATA_DIR = _PKG_DIR / "data"
OUTPUT_DIR = _PKG_DIR.parent / "output"   # jinja_reader/output/
_INIT_DIR = _PKG_DIR / "init_files"

# Template file extensions tried in order
_TEMPLATE_EXTS = (".jinja", ".html")


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------

def _resolve_template(name: str) -> Path:
    """Return the template path for *name*, trying each known extension."""
    for ext in _TEMPLATE_EXTS:
        p = TEMPLATES_DIR / f"{name}{ext}"
        if p.exists():
            return p
    exts = " / ".join(_TEMPLATE_EXTS)
    raise FileNotFoundError(
        f"No template found for '{name}' in {TEMPLATES_DIR}  (tried {exts})"
    )


def _resolve_data(name: str) -> Path:
    """Return the data file path for *name* and error if it doesn't exist."""
    p = DATA_DIR / f"{name}.json"
    if not p.exists():
        raise FileNotFoundError(
            f"No data file found for '{name}'.  "
            f"Expected: {p}"
        )
    return p


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
        pass


class _ReuseAddrServer(socketserver.TCPServer):
    allow_reuse_address = True


def _make_handler(root: Path, live_reload: bool) -> type:
    root_str = str(root)
    base = _LiveReloadHandler if live_reload else http.server.SimpleHTTPRequestHandler

    class Handler(base):  # type: ignore[valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=root_str, **kwargs)  # type: ignore[call-arg]

        def log_message(self, fmt: str, *args: object) -> None:
            pass

    return Handler


def _run_server(port: int, root: Path, live_reload: bool = False) -> None:
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
    idx = html.lower().rfind("</body>")
    if idx == -1:
        return html + _LIVE_RELOAD_SCRIPT
    return html[:idx] + _LIVE_RELOAD_SCRIPT + "\n" + html[idx:]


def _render(
    template_path: Path,
    data_path: Path,
    output_path: Path,
    inject_live_reload: bool = False,
) -> bool:
    try:
        _, context = generate_mock_data(template_path, data_path)
        env = Environment(
            loader=FileSystemLoader(str(template_path.parent)),
            keep_trailing_newline=True,
        )
        env.globals["namespace"] = _MockNamespace
        template = env.get_template(template_path.name)
        rendered = template.render(**context)
        if inject_live_reload:
            rendered = _inject_live_reload(rendered)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
        _last_render_time[0] = time.time()
        return True
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return False


def _watch_loop(
    template_path: Path,
    data_path: Path,
    output_path: Path,
    inject_live_reload: bool = False,
    interval: float = 0.5,
) -> None:
    """Re-render whenever *template_path* or *data_path* changes."""
    last_t = 0.0
    last_d = 0.0
    print(
        f"Watching  {template_path.name}  +  {data_path.name}  →  {output_path}",
        file=sys.stderr,
    )
    print("(Ctrl+C to stop)", file=sys.stderr)
    while True:
        try:
            t_mtime = template_path.stat().st_mtime
            d_mtime = data_path.stat().st_mtime
            if t_mtime != last_t or d_mtime != last_d:
                last_t = t_mtime
                last_d = d_mtime
                if _render(template_path, data_path, output_path, inject_live_reload):
                    changed = "template" if t_mtime != last_t else "data"
                    print(f"[{time.strftime('%H:%M:%S')}] Rendered", file=sys.stderr)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"Watch error: {exc}", file=sys.stderr)
        time.sleep(interval)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _cmd_init(name: str) -> int:
    """Create templates/<name>.jinja and data/<name>.json from the example."""
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    dest_template = TEMPLATES_DIR / f"{name}.jinja"
    dest_data = DATA_DIR / f"{name}.json"

    if dest_template.exists() or dest_data.exists():
        print(
            f"Error: '{name}' already exists.  "
            "Remove the existing files before running init again.",
            file=sys.stderr,
        )
        return 1

    shutil.copy(_INIT_DIR / "example.jinja", dest_template)
    shutil.copy(_INIT_DIR / "example.json", dest_data)

    print(f"Created  {dest_template}")
    print(f"Created  {dest_data}")
    print(f"\nNext steps:")
    print(f"  Edit  {dest_template}")
    print(f"  Edit  {dest_data}")
    print(f"  python run.py {name} --watch --serve")
    return 0


def _cmd_list() -> int:
    """List available templates and whether each has a matching data file."""
    if not TEMPLATES_DIR.exists():
        print("No templates directory found.  Run: python run.py init <name>")
        return 0

    templates = sorted(
        p for p in TEMPLATES_DIR.iterdir()
        if p.suffix in _TEMPLATE_EXTS
    )
    if not templates:
        print("No templates found.  Run: python run.py init <name>")
        return 0

    print("Available templates:\n")
    for tpl in templates:
        name = tpl.stem
        data_file = DATA_DIR / f"{name}.json"
        data_status = "✓ data file" if data_file.exists() else "✗ missing data file"
        print(f"  {name:<24} {tpl.name}  [{data_status}]")
    print()
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    """Resolve paths, then render / watch / serve as requested."""
    try:
        template_path = _resolve_template(args.name)
        data_path = _resolve_data(args.name)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_path = (
        args.output.resolve()
        if args.output
        else OUTPUT_DIR / f"{args.name}.html"
    )
    serve_root = (args.root or output_path.parent).resolve()

    # --list-vars
    if args.list_vars:
        from .mock_data import generate_mock_data as _gmd
        extracted, _ = _gmd(template_path, data_path)
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

    # --json-only
    if args.json_only:
        _, context = generate_mock_data(template_path, data_path)

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
            _render(template_path, data_path, output_path, inject_live_reload=True)
            try:
                rel = str(output_path.relative_to(serve_root)).replace("\\", "/")
            except ValueError:
                rel = output_path.name
            print(f"Serving at  http://127.0.0.1:{args.serve}/{rel}", file=sys.stderr)
            threading.Thread(
                target=_run_server,
                args=(args.serve, serve_root, True),
                daemon=True,
            ).start()
        _watch_loop(template_path, data_path, output_path, inject_live_reload=live)
        return 0

    # --serve only
    if args.serve is not None:
        if not _render(template_path, data_path, output_path):
            return 1
        try:
            rel = str(output_path.relative_to(serve_root)).replace("\\", "/")
        except ValueError:
            rel = output_path.name
        print(f"Serving at  http://127.0.0.1:{args.serve}/{rel}", file=sys.stderr)
        _run_server(args.serve, serve_root)
        return 0

    # Default: single render
    if not _render(template_path, data_path, output_path):
        return 1
    print(f"Rendered  →  {output_path}")
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_SUBCOMMANDS = {"init", "list", "render"}


def main() -> int:
    # Allow `python run.py <name> [flags]` as a shorthand for `render <name>`
    argv = sys.argv[1:]
    if argv and argv[0] not in _SUBCOMMANDS and not argv[0].startswith("-"):
        argv = ["render"] + argv

    parser = argparse.ArgumentParser(
        prog="jinja-reader",
        description="Render a Jinja template with mock data.",
    )
    sub = parser.add_subparsers(dest="command")

    # ── init ──────────────────────────────────────────────────────────
    p_init = sub.add_parser("init", help="Create a starter template + data file")
    p_init.add_argument("name", help="Name for the new template (e.g. invoice)")

    # ── list ──────────────────────────────────────────────────────────
    sub.add_parser("list", help="List available templates")

    # ── render ────────────────────────────────────────────────────────
    p_render = sub.add_parser("render", help="Render a template by name")
    p_render.add_argument("name", help="Template name (e.g. etat_104)")
    _add_render_args(p_render)

    args = parser.parse_args(argv)

    if args.command == "init":
        return _cmd_init(args.name)

    if args.command == "list":
        return _cmd_list()

    if args.command == "render":
        return _cmd_render(args)

    # No arguments — show help + list
    parser.print_help()
    print()
    return _cmd_list()


def _add_render_args(p: argparse.ArgumentParser) -> None:
    """Add render-related flags to an argument parser."""
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="Override output file path")
    p.add_argument("--json-only", action="store_true",
                   help="Print mock context as JSON and exit")
    p.add_argument("--list-vars", action="store_true",
                   help="Print extracted variable paths and exit")
    p.add_argument("--watch", action="store_true",
                   help="Re-render on template or data file change")
    p.add_argument("--serve", type=int, nargs="?", const=3000, metavar="PORT",
                   help="Serve output on 127.0.0.1 (default port 3000)")
    p.add_argument("--root", type=Path, default=None,
                   help="Document root for --serve (default: output directory)")


if __name__ == "__main__":
    sys.exit(main())
