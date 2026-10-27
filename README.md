# FFP — Foxmayn Frappe Print

FFP previews Frappe / ERPNext print formats (Jinja) outside a Frappe site. You write the template and a small JSON data file. FFP renders HTML with mock `doc` and `frappe` objects, and reloads the browser when you save. No bench, no site, no database.

FFP is part of the Foxmayn Frappe tools:

- [FFC](https://github.com/nasroykh/foxmayn_frappe_cli) — Frappe CLI
- [FFM](https://github.com/nasroykh/foxmayn_frappe_manager) — Frappe manager
- [FFT](https://github.com/nasroykh/foxmayn_frappe_types) — Frappe types

More at [foxmayn.com](https://foxmayn.com).

## Install

Needs Python 3.10+.

```bash
pipx install foxmayn-ffp     # recommended
# or
pip install foxmayn-ffp
```

The command is `ffp`. The Python import package is `jinja_reader`.

## Usage

FFP works in the current directory. It reads `templates/<name>.jinja` and `data/<name>.json`, and writes `output/<name>.html`.

```bash
ffp init invoice                       # create templates/invoice.jinja + data/invoice.json
ffp invoice                            # render once (same as: ffp render invoice)
ffp invoice --watch --serve            # render, serve on 127.0.0.1:3000, live reload
ffp list                               # list templates and their data files
```

Open `http://127.0.0.1:3000/invoice.html`. The page reloads when you save the template or the JSON.

| Flag                 | Description                                                  |
| -------------------- | ------------------------------------------------------------ |
| `-o / --output PATH` | Output file path                                             |
| `--watch`            | Re-render when the template or its data file changes         |
| `--serve [PORT]`     | Serve output on `127.0.0.1` (default port 3000)              |
| `--root PATH`        | Document root for `--serve` (for absolute asset paths)       |
| `--list-vars`        | Print the variables found in the template and exit           |
| `--json-only`        | Print the mock context as JSON and exit                      |

Template extensions tried, in order: `.jinja`, `.html`, `.html.jinja`, `.jinja.html`. `{% include %}`, `{% extends %}` and macros resolve from the `templates/` directory.

## Minimal example

`templates/invoice.jinja`:

```jinja
<h1>{{ doc.title }}</h1>
<p>Total: {{ doc.get_formatted("grand_total") }}</p>
{% for row in doc.items %}
  <div>{{ row.description }} — {{ row.get_formatted("amount") }}</div>
{% endfor %}
```

`data/invoice.json`:

```json
{
  "title": "Invoice 1",
  "grand_total": 1234.5,
  "items": [
    { "description": "Widget", "amount": 10 },
    { "description": "Gadget", "amount": 2500.5 }
  ]
}
```

`ffp invoice` writes `output/invoice.html`. A field not in the JSON gets a heuristic mock value (for example `Mock remarks`). Keys starting with `_` are comments; `_page_size` sets rows per page, and `doc.pages` is derived from the length of the child table.

## What the mocks do

FFP reads the template with the Jinja2 AST, finds which names it uses, and builds a context. `doc` becomes a `DocMock`, `frappe` becomes a `FrappeMock`, and rows of child tables under `doc` become `DocMock` too. Any other root name becomes a plain dict.

| Frappe API                         | FFP behaviour                                                        |
| ---------------------------------- | -------------------------------------------------------------------- |
| `doc.fieldname`                    | Value from the JSON; fields the template uses but the JSON lacks get a mock |
| `doc.get("field", default)`        | Dict-style lookup with default                                       |
| `doc["field"]`                     | Dict-style lookup (raises `KeyError` if absent)                      |
| `doc.get_formatted("field")`       | Numbers: space thousands, comma decimals; adds ` DA` when the field name contains `total` or `sales`; other values as text; none as `""` |
| `doc.items` (child table)          | List of `DocMock` rows from the JSON array                           |
| `frappe.format(value)`             | `str(value)`, `""` for none (no field-type formatting)               |
| `frappe.format_currency(value)`    | Same number style as above with ` DA` suffix                         |
| `frappe._("text")`                 | Returns the text unchanged                                           |
| `frappe.<other>(...)`              | Returns `None`                                                       |
| `namespace(...)`                   | Gains a `get_formatted()` method                                     |

## Limits

- Not a Frappe runtime. No database, no `frappe.db`, no permissions, no hooks.
- `frappe.format` does not use field types. `frappe.format_currency` ignores the currency and precision arguments and always uses the French-style number format with ` DA`.
- Unknown flat calls like `frappe.get_doc(...)` return `None`. Nested namespaces such as `frappe.utils.nowdate()` or `frappe.db.get_value()` are not mocked and fail the render with an error.
- No translations, no `get_formatted` field-type or currency awareness, no print settings, letter heads, `no_letterhead`, or `print_format` JSON/Print Designer layouts.
- Python-side print format logic (server scripts, `jinja` hooks methods) is not run.
- Only `doc` rows are wrapped in `DocMock`; rows under other roots are plain dicts.
- Undefined variables do not raise: names the template uses are always mocked, and a field the mock lacks reads as `None`.
- Number and currency style is fixed (French locale, `DA`). It is not read from the data file.
- Output is HTML only. FFP does not make PDFs.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest
```

## License

MIT
