# Changelog

## 1.0.0

First public release as FFP (Foxmayn Frappe Print), part of the Foxmayn Frappe tools.

- Preview Frappe / ERPNext print formats (Jinja) outside a Frappe site.
- `DocMock` and `FrappeMock` stand in for `doc` and `frappe`.
- Mock data from the template's variables plus a per-template JSON file.
- `--watch` and `--serve` for live reload.
- Published as `foxmayn-ffp` with an `ffp` command.
- `templates/`, `data/` and `output/` now live in the current working directory, not inside the installed package.
