# jinja_reader

Standalone Jinja template renderer with mock data generation and live reload.

## Requirements

- Python 3.10+
- `pip install jinja2`

## Installation

```bash
cd jinja_reader
pip install jinja2           # run anywhere — no install needed
# or: pip install -e .       # installs the `jinja-reader` command globally
```

## Folder structure

```
jinja_reader/
├── run.py                         # standalone launcher
├── jinja_reader/
│   ├── templates/                 # your Jinja templates go here
│   │   └── example.jinja
│   ├── data/                      # one JSON data file per template
│   │   └── example.json
│   └── init_files/                # bundled example (do not edit)
└── output/                        # rendered HTML (generated, do not edit)
    └── example.html
```

Each template has a matching JSON data file with the same stem name.

## Quick start

```bash
# 1. Create a starter template + data file
python run.py init my_template

# 2. Edit the generated files
#    jinja_reader/templates/my_template.jinja
#    jinja_reader/data/my_template.json

# 3. Render, serve, and live-reload in one command
python run.py my_template --watch --serve
```

Open `http://127.0.0.1:3000/my_template.html` — the browser reloads
automatically whenever you save the template or its data file.

## Commands

### `init <name>`

Creates `templates/<name>.jinja` and `data/<name>.json` from the bundled
example.  Both files are fully annotated so you can see how everything fits
together.

```bash
python run.py init invoice
```

### `list`

Lists all templates and whether each one has a matching data file.

```bash
python run.py list
```

### `render <name>` (or bare `<name>`)

Renders the named template and writes the output to `output/<name>.html`.

```bash
python run.py render etat_104
python run.py etat_104          # identical shorthand
```

| Flag                  | Description                                                    |
| --------------------- | -------------------------------------------------------------- |
| `-o / --output PATH`  | Override output file path                                      |
| `--watch`             | Re-render whenever the template **or** its data file changes   |
| `--serve [PORT]`      | Serve output on `127.0.0.1` (default port 3000)                |
| `--root PATH`         | Document root for `--serve` (default: output directory)        |
| `--list-vars`         | Print all extracted variable paths and exit                    |
| `--json-only`         | Print the mock context as JSON and exit                        |

### Examples

```bash
# One-shot render
python run.py etat_104

# Dev mode with live reload
python run.py etat_104 --watch --serve

# If assets use absolute paths (e.g. /files/logo.png), serve from the parent:
python run.py etat_104 --watch --serve --root ..

# Inspect extracted variables
python run.py etat_104 --list-vars

# Dump mock context as JSON
python run.py etat_104 --json-only
```

## How mock data is generated

1. **Parses** the template using the Jinja2 AST (not regex) to extract:
   - All context variable paths (`doc.company_name`, `sale.customer_rc`, …)
   - Iterable paths (`doc.sales`, `doc.items`, …)
   - Loop variable mappings (`doc.sales` → loop var `sale`)

   Locally-defined names from `{% set %}` and `{% for %}` targets are excluded
   so only genuine context inputs are reported.

2. **Loads values** from `data/<name>.json`.  Every key in the JSON file
   becomes an overridable mock value.  Edit the JSON — no Python changes needed.

3. **Builds the context** for each root name found in the template:
   - `doc` → wrapped in `DocMock` (supports `doc.get_formatted('field')`,
     attribute access, and French-locale number formatting).
   - `frappe` → wrapped in `FrappeMock` (stubs `frappe.format()`,
     `frappe.format_currency()`, translations, etc.).
   - Loop items (e.g. each `sale` in `doc.sales`) → also wrapped in `DocMock`
     so `sale.get_formatted(...)` works inside loops.
   - Jinja2 `namespace()` objects → extended with `get_formatted()` so
     accumulator namespaces in paginated templates work correctly.
   - Other roots → plain dicts.

4. **Renders** with a `FileSystemLoader` rooted at the template directory,
   so `{% include %}`, `{% extends %}`, and neighbouring macros all resolve.

5. **Live reload**: `--watch --serve` starts a local HTTP server on
   `127.0.0.1`, monitors both the template and data files for changes, and
   injects a 300 ms polling script so the browser reloads automatically.

## Notes

- The files inside `output/` are **generated artifacts** — do not edit them
  directly; edit the template and data files instead.
- If your template references assets with absolute paths (e.g. `/style.css`,
  `/files/image.png`), pass `--root <dir>` to serve from the directory that
  actually contains those files.
