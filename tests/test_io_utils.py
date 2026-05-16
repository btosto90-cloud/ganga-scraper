"""Tests para io_utils.atomic_write_json."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from io_utils import atomic_write_json


def test_writes_valid_json(tmp_path):
    path = tmp_path / "out.json"
    atomic_write_json(str(path), {'a': 1, 'b': [2, 3]})
    with open(path) as f:
        assert json.load(f) == {'a': 1, 'b': [2, 3]}


def test_tmp_file_is_removed(tmp_path):
    path = tmp_path / "out.json"
    atomic_write_json(str(path), {'x': 1})
    assert not (tmp_path / "out.json.tmp").exists()


def test_overwrites_existing_file(tmp_path):
    path = tmp_path / "out.json"
    path.write_text('{"old": true}')
    atomic_write_json(str(path), {'new': True})
    with open(path) as f:
        assert json.load(f) == {'new': True}


def test_preserves_existing_on_failure(tmp_path):
    """Si la escritura del tmp falla (data no serializable), el archivo
    original queda intacto y el tmp limpio."""
    path = tmp_path / "out.json"
    path.write_text('{"original": true}')
    try:
        atomic_write_json(str(path), {'bad': object()})  # objects no son JSON serializable
    except TypeError:
        pass
    with open(path) as f:
        assert json.load(f) == {'original': True}


def test_unicode_preserved(tmp_path):
    path = tmp_path / "out.json"
    atomic_write_json(str(path), {'marca': 'peugeot', 'msg': '¡ganga!'})
    with open(path, encoding='utf-8') as f:
        text = f.read()
    assert 'ganga' in text
    assert '¡' in text  # ensure_ascii=False mantiene unicode literal
