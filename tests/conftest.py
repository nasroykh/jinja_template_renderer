import json

import pytest

from jinja_reader import main as ffp_main


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """Point FFP's templates/data/output dirs at a temp project."""
    (tmp_path / "templates").mkdir()
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(ffp_main, "TEMPLATES_DIR", tmp_path / "templates")
    monkeypatch.setattr(ffp_main, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(ffp_main, "OUTPUT_DIR", tmp_path / "output")
    return tmp_path


@pytest.fixture
def make_project(workdir):
    def _make(name, template, data):
        (workdir / "templates" / f"{name}.jinja").write_text(template, encoding="utf-8")
        (workdir / "data" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
        return workdir

    return _make
