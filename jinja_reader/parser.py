"""Extract variable references from Jinja templates using the Jinja2 AST."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Set

from jinja2 import Environment as _JinjaEnv
from jinja2 import nodes as _jnodes

# Jinja2 built-in names that must never appear as context variables
_BUILTINS: frozenset[str] = frozenset({
    "loop", "super", "caller", "varargs", "kwargs",
    "true", "false", "none", "True", "False", "None",
    "range", "lipsum", "dict", "joiner", "cycler", "namespace",
})


@dataclass
class ExtractedVariables:
    """Variables found in a Jinja template."""

    # Dotted paths accessed from context or loop variables: "doc.company_name"
    variable_paths: Set[str] = field(default_factory=set)
    # Top-level context root names that are NOT loop variables: "doc"
    root_names: Set[str] = field(default_factory=set)
    # Dotted paths iterated over in {% for %}: "doc.sales"
    iterable_paths: Set[str] = field(default_factory=set)
    # Mapping iterable_path -> loop variable name: "doc.sales" -> "sale"
    loop_vars: dict[str, str] = field(default_factory=dict)


def extract_variables_from_template(source: str) -> ExtractedVariables:
    """
    Parse a Jinja template using the Jinja2 AST and extract all variable
    references.  Locally-defined names ({% set %} and {% for %} targets) are
    excluded from ``root_names`` so only real context inputs are reported.
    """
    result = ExtractedVariables()
    env = _JinjaEnv()
    try:
        ast = env.parse(source)
    except Exception:
        return result

    locals_ = frozenset(_collect_locals(ast))
    _walk(ast, result, locals_)
    return result


def read_template(path: str | Path) -> str:
    """Read template source from disk."""
    return Path(path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _collect_locals(ast_root: _jnodes.Template) -> set[str]:
    """
    Collect every name defined by ``{% set %}`` or as a ``{% for %}`` target
    anywhere in the template.  These names should not be treated as context
    variables when generating mock data.
    """
    names: set[str] = set()
    for node in ast_root.find_all(_jnodes.Assign):
        if isinstance(node.target, _jnodes.Name):
            names.add(node.target.name)
    for node in ast_root.find_all(_jnodes.For):
        tgt = node.target
        if isinstance(tgt, _jnodes.Name):
            names.add(tgt.name)
        elif isinstance(tgt, _jnodes.Tuple):
            for item in tgt.items:
                if isinstance(item, _jnodes.Name):
                    names.add(item.name)
    return names


def _attr_chain(node: _jnodes.Node) -> str | None:
    """
    Build a dotted attribute path from a chain of Getattr/Getitem nodes.
    Returns ``None`` when the expression cannot be reduced to a simple path.
    Subscripts/slices are ignored so ``doc.sales[0:23]`` -> ``"doc.sales"``.
    """
    if isinstance(node, _jnodes.Name):
        return node.name
    if isinstance(node, _jnodes.Getattr):
        parent = _attr_chain(node.node)
        if parent is not None:
            return f"{parent}.{node.attr}"
    if isinstance(node, _jnodes.Getitem):
        return _attr_chain(node.node)
    return None


def _record_path(path: str, root: str, result: ExtractedVariables, locals_: frozenset[str]) -> None:
    """Add a dotted path to result if root is not a Jinja built-in."""
    if root in _BUILTINS:
        return
    result.variable_paths.add(path)
    if root not in locals_:
        result.root_names.add(root)


def _walk(node: _jnodes.Node, result: ExtractedVariables, locals_: frozenset[str]) -> None:
    """Recursively walk an AST node and populate *result*."""

    if isinstance(node, _jnodes.For):
        # Process iterable expression in current scope
        _walk(node.iter, result, locals_)

        iter_path = _attr_chain(node.iter)
        if iter_path and "." in iter_path:
            result.iterable_paths.add(iter_path)

        # Map iterable path to loop variable name
        if isinstance(node.target, _jnodes.Name) and iter_path:
            result.loop_vars[iter_path] = node.target.name

        # Process loop body (loop variable itself stays in locals_ — it is
        # already tracked in loop_vars and will be handled by mock_data)
        for child in node.body:
            _walk(child, result, locals_)
        for child in node.else_:
            _walk(child, result, locals_)
        return

    if isinstance(node, _jnodes.Call):
        # Special case: obj.get_formatted('field_name')
        # Instead of treating get_formatted as a field, extract obj.field_name.
        if (
            isinstance(node.node, _jnodes.Getattr)
            and node.node.attr == "get_formatted"
            and node.args
            and isinstance(node.args[0], _jnodes.Const)
            and isinstance(node.args[0].value, str)
        ):
            obj_path = _attr_chain(node.node.node)
            if obj_path:
                fieldname = node.args[0].value
                full_path = f"{obj_path}.{fieldname}"
                root = obj_path.split(".")[0]
                _record_path(full_path, root, result, locals_)
            return
        for child in node.iter_child_nodes():
            _walk(child, result, locals_)
        return

    if isinstance(node, _jnodes.Getattr):
        path = _attr_chain(node)
        if path and "." in path:
            root = path.split(".")[0]
            _record_path(path, root, result, locals_)
        return  # Chain fully captured — do not recurse further

    if isinstance(node, _jnodes.Name):
        name = node.name
        if name not in _BUILTINS and name not in locals_:
            result.root_names.add(name)
        return

    for child in node.iter_child_nodes():
        _walk(child, result, locals_)
