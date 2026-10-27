import json

from jinja_reader import __version__
from jinja_reader.main import main
from jinja_reader.mock_data import DocMock, FrappeMock, generate_mock_data

INVOICE = """\
<h1>{{ doc.title }}</h1>
<p>{{ doc.get_formatted('grand_total') }}</p>
{% for row in doc.items %}
<tr><td>{{ row.description }}</td><td>{{ row.get_formatted('amount') }}</td></tr>
{% endfor %}
"""

DATA = {
    "title": "Invoice 1",
    "grand_total": 1234.5,
    "items": [
        {"description": "Widget", "amount": 10},
        {"description": "Gadget", "amount": 2500.5},
    ],
}


def run(argv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["ffp", *argv])
    return main()


def test_version():
    assert __version__ == "1.0.0"


def test_render_fields_and_child_table(make_project, monkeypatch):
    p = make_project("inv", INVOICE, DATA)
    assert run(["inv"], monkeypatch) == 0
    html = (p / "output" / "inv.html").read_text(encoding="utf-8")
    assert "<h1>Invoice 1</h1>" in html
    assert "Widget" in html and "Gadget" in html
    assert html.count("<tr>") == 2


def test_get_formatted_number_french_locale(make_project, monkeypatch):
    p = make_project("inv", INVOICE, DATA)
    run(["inv"], monkeypatch)
    html = (p / "output" / "inv.html").read_text(encoding="utf-8")
    # grand_total -> thousands thin space, decimal comma, " DA" suffix
    assert "1 234,50 DA" in html
    # child-row amount: no total/sales in name, no suffix
    assert "2 500,50<" in html


def test_custom_output_path(make_project, monkeypatch, tmp_path):
    make_project("inv", INVOICE, DATA)
    out = tmp_path / "x" / "out.html"
    assert run(["inv", "-o", str(out)], monkeypatch) == 0
    assert out.exists()


def test_frappe_helpers_render(make_project, monkeypatch):
    tpl = (
        "{{ frappe.format(doc.status) }}|{{ frappe.format_currency(1500) }}|"
        "{{ frappe._('Hello') }}|[{{ frappe.format(None) }}]"
    )
    p = make_project("f", tpl, {"status": "Open"})
    assert run(["f"], monkeypatch) == 0
    html = (p / "output" / "f.html").read_text(encoding="utf-8")
    assert html == "Open|1 500,00 DA|Hello|[]"


def test_frappe_mock_unit():
    f = FrappeMock()
    assert f.format(None) == ""
    assert f.format(5) == "5"
    assert f.format_currency(None) == ""
    assert f.format_currency("abc") == "abc"
    assert f.format_currency(1234.5) == "1 234,50 DA"
    assert f._("x") == "x"
    assert f.whatever_unmocked() is None


def test_doc_mock_unit():
    d = DocMock({"name": "A", "total": 3, "note": "hi", "none": None})
    assert d.name == "A"
    assert d.missing is None
    assert d.get("missing", 7) == 7
    assert d["name"] == "A"
    assert d.get_formatted("none") == ""
    assert d.get_formatted("note") == "hi"
    assert d.get_formatted("total") == "3,00 DA"
    assert d.to_dict()["name"] == "A"


def test_namespace_get_formatted(make_project, monkeypatch):
    tpl = "{% set ns = namespace(sum=0) %}{% set ns.sum = 1234.5 %}{{ ns.get_formatted('sum') }}"
    p = make_project("ns", tpl, {})
    assert run(["ns"], monkeypatch) == 0
    assert (p / "output" / "ns.html").read_text(encoding="utf-8") == "1 234,50"


def test_missing_data_values_get_mock_fallback(make_project):
    p = make_project("m", "{{ doc.remarks }}", {})
    _, ctx = generate_mock_data(p / "templates" / "m.jinja", p / "data" / "m.json")
    assert ctx["doc"].remarks == "Mock remarks"


def test_pages_derived_from_page_size(make_project):
    data = {"_page_size": 2, "items": [{"description": str(i)} for i in range(5)]}
    p = make_project("pg", INVOICE, data)
    _, ctx = generate_mock_data(p / "templates" / "pg.jinja", p / "data" / "pg.json")
    assert ctx["doc"].pages == 3


def test_missing_template_errors(workdir, monkeypatch, capsys):
    (workdir / "data" / "ghost.json").write_text("{}")
    assert run(["ghost"], monkeypatch) == 1
    assert "No template found for 'ghost'" in capsys.readouterr().err


def test_missing_data_file_errors(workdir, monkeypatch, capsys):
    (workdir / "templates" / "nodata.jinja").write_text("hi")
    assert run(["nodata"], monkeypatch) == 1
    assert "No data file found for 'nodata'" in capsys.readouterr().err


def test_template_syntax_error_fails(make_project, monkeypatch, capsys):
    p = make_project("bad", "{% for x in doc.items %}", {})
    assert run(["bad"], monkeypatch) == 1
    assert "Error:" in capsys.readouterr().err
    assert not (p / "output" / "bad.html").exists()


def test_unmocked_frappe_namespace_fails(make_project, monkeypatch, capsys):
    # frappe.utils.* is not mocked; flat unknown calls return None, nested ones error.
    make_project("u", "{{ frappe.utils.nowdate() }}", {})
    assert run(["u"], monkeypatch) == 1
    assert "nowdate" in capsys.readouterr().err


def test_unmocked_flat_frappe_call_renders_empty(make_project, monkeypatch):
    p = make_project("u2", "[{{ frappe.get_value('X', 'y') or '' }}]", {})
    assert run(["u2"], monkeypatch) == 0
    assert (p / "output" / "u2.html").read_text(encoding="utf-8") == "[]"


def test_json_only(make_project, monkeypatch, capsys):
    make_project("inv", INVOICE, DATA)
    assert run(["inv", "--json-only"], monkeypatch) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["doc"]["title"] == "Invoice 1"
    assert out["doc"]["items"][0]["description"] == "Widget"


def test_list_vars(make_project, monkeypatch, capsys):
    make_project("inv", INVOICE, DATA)
    assert run(["inv", "--list-vars"], monkeypatch) == 0
    out = capsys.readouterr().out
    assert "doc.items" in out and "doc.title" in out


def test_init_then_render_and_refuse_overwrite(workdir, monkeypatch, capsys):
    assert run(["init", "demo"], monkeypatch) == 0
    assert (workdir / "templates" / "demo.jinja").exists()
    assert (workdir / "data" / "demo.json").exists()
    assert run(["init", "demo"], monkeypatch) == 1
    assert run(["demo"], monkeypatch) == 0
    assert (workdir / "output" / "demo.html").exists()


def test_list(make_project, monkeypatch, capsys):
    make_project("inv", INVOICE, DATA)
    assert run(["list"], monkeypatch) == 0
    assert "inv" in capsys.readouterr().out
