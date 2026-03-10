# jinja_reader

Standalone Jinja template renderer with mock data generation.

## Requirements

- Python 3.10+
- `pip install jinja2`

## Installation

```bash
cd jinja_reader
pip install jinja2           # run anywhere — no install needed
# or: pip install -e .       # installs the `jinja-reader` command
```

## Usage

The default template is `template.jinja` in the current directory.

```bash
# Render once, write to index.html
python run.py

# Render a different template
python run.py path/to/my.jinja -o out.html

# Dev mode: re-render on save + serve + live reload
python run.py --watch --serve

# If assets use absolute paths (e.g. /style.css) serve from the parent:
python run.py --watch --serve --root ..

# List variables extracted from the template
python run.py --list-vars

# Dump mock context as JSON
python run.py --json-only
```

### Options

| Flag                 | Description                                                   |
| -------------------- | ------------------------------------------------------------- |
| `template`           | Path to Jinja template (default: `template.jinja`)            |
| `-o / --output PATH` | Output file (default: `index.html` next to template)          |
| `--watch`            | Re-render whenever the template file changes                  |
| `--serve [PORT]`     | Serve the output directory on `127.0.0.1` (default port 3000) |
| `--root PATH`        | Document root for `--serve` (default: output directory)       |
| `--list-vars`        | Print all variable paths extracted from the template and exit |
| `--json-only`        | Print mock context as JSON and exit                           |

## How it works

1. **Parses** the template using the Jinja2 AST — not regex — to reliably find context variable paths, iterable paths, and `{% for %}` loop variable mappings.  Locally-defined names (`{% set %}` targets and loop variables) are excluded from the reported inputs so only real context variables appear.

2. **Generates mock data** for every extracted variable.  Iterable paths (e.g. `doc.sales`) are populated with lists whose item structure is derived from the loop variable's field accesses (e.g. `sale.customer_name`).  The `doc` root is wrapped in a `DocMock` object which also supports `doc.get_formatted('field')`.

3. **Renders** using a `FileSystemLoader` rooted at the template directory, so `{% include %}`, `{% extends %}`, and neighboring macros work.

4. **Dev server**: `--watch --serve` starts a local HTTP server on `127.0.0.1` and injects a polling live-reload script into the rendered output, so the browser refreshes automatically after each save.

## Notes

- The rendered `index.html` is a **generated artifact** — do not edit it directly.
- If your template references assets with absolute paths (e.g. `/style.css`, `/files/image.png`), pass `--root <parent>` to serve from the directory that actually contains those files.
- Tested against `template.jinja` in this repository but works with any Jinja2 template that uses a top-level context object.
