"""Generate mock data for Jinja template variables."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

from .parser import ExtractedVariables, extract_variables_from_template, read_template


class DocMock:
    """
    Mock object that mimics the Frappe Document API.
    Supports attribute access (doc.field) and doc.get_formatted('field').
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._data.get(name)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def get_formatted(self, fieldname: str) -> str:
        """
        Return a display-formatted value.
        Numbers are formatted in French locale style (space thousands, comma decimal).
        Currency fields are suffixed with ' DA'.
        """
        val = self._data.get(fieldname)
        if val is None:
            return ""
        if isinstance(val, (int, float)):
            s = f"{val:,.2f}".replace(",", "\u2009").replace(".", ",")
            if "total" in fieldname.lower() or "sales" in fieldname.lower():
                return f"{s} DA"
            return s
        return str(val)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain serialisable dict (for --json-only)."""
        return dict(self._data)


class FrappeMock:
    """
    Stub for the ``frappe`` module in templates.
    Provides no-op versions of the most common Frappe utility functions so
    templates that call e.g. ``frappe.format(...)`` render without errors.
    """

    def format(self, value: Any, df: Any = None, doc: Any = None, currency: Any = None) -> str:
        """Return a human-readable string for any value."""
        if value is None:
            return ""
        return str(value)

    def format_currency(self, value: Any, currency: Any = None, precision: Any = None) -> str:
        if value is None:
            return ""
        try:
            s = f"{float(value):,.2f}".replace(",", "\u2009").replace(".", ",")
            return f"{s} DA"
        except (TypeError, ValueError):
            return str(value)

    def _(self, text: str, *args: Any, **kwargs: Any) -> str:
        """Translation stub — returns text as-is."""
        return text

    def __getattr__(self, name: str) -> Any:
        """Return a silent no-op callable for any unknown frappe utility."""
        def _noop(*args: Any, **kwargs: Any) -> Any:
            return None
        return _noop


# ---------------------------------------------------------------------------
# Data file loader
# ---------------------------------------------------------------------------

def load_data_file(data_path: Path) -> tuple[dict[str, Any], int]:
    """Load a template's JSON data file.

    Returns (field_mocks, page_size) where:
    - field_mocks: data dict with comment keys (starting with "_") stripped
    - page_size: rows per page for the fallback mock generator, taken from the
      optional ``_page_size`` JSON key (default 23)
    """
    data = json.loads(data_path.read_text(encoding="utf-8"))
    page_size = int(data.get("_page_size", 23))
    return {k: v for k, v in data.items() if not k.startswith("_")}, page_size


# ---------------------------------------------------------------------------
# Mock value heuristics (fallback when a field is not in the data file)
# ---------------------------------------------------------------------------

def _mock_value(field_name: str, field_mocks: dict[str, Any], index: int = 0) -> Any:
    """Return a plausible mock value for a field, using *index* to vary items."""
    val = field_mocks.get(field_name)
    if val is not None:
        return val

    name = field_name.lower()
    if "total" in name or "sales" in name:
        return float(random.randint(10_000, 500_000))
    if "nif" in name:
        return f"000{1_000_000_000_000 + index:013d}"
    if "rc" in name:
        return f"16/00-{100_000 + index}-{chr(65 + index % 26)}12"
    if "ai" in name:
        return f"{100_000_000_000_000 + index:015d}"
    if "forme_juridique" in name:
        return random.choice(["SARL", "EURL", "SPA", "SNC"])
    if "name" in name:
        return f"Item {index + 1}"
    if "address" in name:
        return f"{index + 1} Rue Example, 16000"
    return f"Mock {field_name}"


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def build_mock_context(
    extracted: ExtractedVariables, field_mocks: dict[str, Any], page_size: int = 23
) -> dict[str, Any]:
    """
    Build a complete Jinja context dict from extracted variable information.

    For each root name found in the template:
    - Scalar fields are populated from *field_mocks* (the template's JSON data
      file) or via heuristic fallbacks.
    - Iterable fields (e.g. doc.sales) are populated with a list of item dicts
      whose keys come from the loop variable's field accesses.
    - The ``doc`` root is wrapped in DocMock for Frappe API compatibility.
    """
    context: dict[str, Any] = {}

    loop_var_names = set(extracted.loop_vars.values())

    # Group extracted paths by root
    root_fields: dict[str, set[str]] = {}
    for path in extracted.variable_paths:
        root, _, rest = path.partition(".")
        if rest:
            root_fields.setdefault(root, set()).add(rest)

    def _iterable_fields_for(root: str) -> set[str]:
        prefix = root + "."
        result: set[str] = set()
        for ip in extracted.iterable_paths:
            if ip.startswith(prefix):
                result.add(ip[len(prefix):].split(".")[0])
        return result

    for root in extracted.root_names:
        if root in loop_var_names:
            continue

        obj: dict[str, Any] = {}
        iterable_fields = _iterable_fields_for(root)

        for field in root_fields.get(root, set()):
            immediate = field.split(".")[0]
            if immediate in iterable_fields:
                continue
            obj[immediate] = _mock_value(field, field_mocks, 0)

        # Process iterable fields first so we can derive `pages` from real data.
        _page_size = page_size

        for iter_path, loop_var in extracted.loop_vars.items():
            if not iter_path.startswith(root + "."):
                continue
            list_field = iter_path[len(root) + 1:].split(".")[0]
            item_fields = root_fields.get(loop_var, set())

            raw_list = field_mocks.get(list_field)
            if isinstance(raw_list, list):
                # Use the actual items from the JSON data file and derive pages.
                items: list[Any] = [
                    DocMock(item) if root == "doc" else item
                    for item in raw_list
                ]
                obj["pages"] = max(1, math.ceil(len(items) / _page_size))
            else:
                # Fall back to generating mock items based on the pages field.
                pages = obj.get("pages", 2) if isinstance(obj.get("pages"), int) else 2
                count = max(pages * _page_size, 25)
                items = []
                for i in range(count):
                    item_dict = {
                        f.split(".")[0]: _mock_value(f.split(".")[0], field_mocks, i)
                        for f in item_fields
                    }
                    # Wrap in DocMock so get_formatted() works on loop items
                    items.append(DocMock(item_dict) if root == "doc" else item_dict)

            obj[list_field] = items

        if root == "frappe":
            context[root] = FrappeMock()
        elif root == "doc":
            context[root] = DocMock(obj)
        else:
            context[root] = obj

    return context


def generate_mock_data(
    template_path: str | Path,
    data_path: str | Path,
) -> tuple[ExtractedVariables, dict[str, Any]]:
    """Read a template + its data file, and return (extracted, context)."""
    source = read_template(template_path)
    extracted = extract_variables_from_template(source)
    field_mocks, page_size = load_data_file(Path(data_path))
    context = build_mock_context(extracted, field_mocks, page_size)
    return extracted, context
