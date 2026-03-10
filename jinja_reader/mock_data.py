"""Generate mock data for Jinja template variables."""

from __future__ import annotations

import json
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


# ---------------------------------------------------------------------------
# Known mock values — loaded from data/mock_data.json at import time.
# Edit that file to change mock values without touching Python code.
# ---------------------------------------------------------------------------

_DATA_FILE = Path(__file__).parent / "data" / "mock_data.json"


def _load_field_mocks() -> dict[str, Any]:
    data = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    # Strip comment keys (JSON has no native comment syntax)
    return {k: v for k, v in data.items() if not k.startswith("_")}


_FIELD_MOCKS: dict[str, Any] = _load_field_mocks()


def _mock_value(field_name: str, index: int = 0) -> Any:
    """Return a plausible mock value for a field, using *index* to vary items."""
    val = _FIELD_MOCKS.get(field_name)
    if val is not None:
        return val() if callable(val) else val

    name = field_name.lower()
    if "total" in name or "sales" in name:
        return float(1000) if "tva" not in name else float(10000)
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


def build_mock_context(extracted: ExtractedVariables) -> dict[str, Any]:
    """
    Build a complete Jinja context dict from extracted variable information.

    For each root name found in the template:
    - Scalar fields are populated with mock values.
    - Iterable fields (e.g. doc.sales) are populated with a list of item
      dicts whose keys come from the corresponding loop variable's field
      accesses (e.g. sale.customer_name -> {"customer_name": ...}).
    - The ``doc`` root is wrapped in DocMock for Frappe API compatibility.
    """
    context: dict[str, Any] = {}

    # Names that come from {% for %} targets — not top-level context roots
    loop_var_names = set(extracted.loop_vars.values())

    # Group extracted paths by root
    root_fields: dict[str, set[str]] = {}
    for path in extracted.variable_paths:
        root, _, rest = path.partition(".")
        if rest:
            root_fields.setdefault(root, set()).add(rest)

    # Which immediate fields of a root are actually iterable paths?
    def _iterable_fields_for(root: str) -> set[str]:
        prefix = root + "."
        result: set[str] = set()
        for ip in extracted.iterable_paths:
            if ip.startswith(prefix):
                # e.g. "doc.sales" -> first segment after root = "sales"
                segment = ip[len(prefix) :].split(".")[0]
                result.add(segment)
        return result

    for root in extracted.root_names:
        if root in loop_var_names:
            continue  # derived via loop, not a direct context variable

        obj: dict[str, Any] = {}
        iterable_fields = _iterable_fields_for(root)

        # Populate scalar fields
        for field in root_fields.get(root, set()):
            immediate = field.split(".")[0]
            if immediate in iterable_fields:
                continue  # handled below
            obj[immediate] = _mock_value(field, 0)

        # Ensure pages is an int for range() usage in templates
        if "pages" in obj and not isinstance(obj["pages"], int):
            obj["pages"] = 2
        pages = obj.get("pages", 2) if isinstance(obj.get("pages"), int) else 2

        # Build lists for iterable fields
        for iter_path, loop_var in extracted.loop_vars.items():
            if not iter_path.startswith(root + "."):
                continue
            list_field = iter_path[len(root) + 1 :].split(".")[0]

            # Fields accessed on the loop variable (e.g. sale.customer_name)
            item_fields = root_fields.get(loop_var, set())

            # Use pages * 23 to ensure enough rows for paginated templates
            count = max(pages * 23, 25)

            items = []
            for i in range(count):
                item = {
                    f.split(".")[0]: _mock_value(f.split(".")[0], i)
                    for f in item_fields
                }
                items.append(item)

            obj[list_field] = items

        context[root] = DocMock(obj) if root == "doc" else obj

    return context


def generate_mock_data(
    template_path: str | Path,
) -> tuple[ExtractedVariables, dict[str, Any]]:
    """Read a template, extract variables, and return (extracted, context)."""
    source = read_template(template_path)
    extracted = extract_variables_from_template(source)
    context = build_mock_context(extracted)
    return extracted, context
