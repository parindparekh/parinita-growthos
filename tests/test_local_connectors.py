import json

import pytest

from scripts.local_connectors import load_connector_secrets


def test_missing_file_does_not_invent_credentials(tmp_path):
    assert load_connector_secrets(tmp_path / "missing.json") == {}


def test_explicit_connector_credentials(tmp_path):
    path = tmp_path / "credentials.json"
    expected = {"GROWTHOS_SECRET_REDDIT_CLIENT_SECRET": "synthetic-test-value"}
    path.write_text(json.dumps(expected), encoding="utf-8")
    assert load_connector_secrets(path) == expected


@pytest.mark.parametrize("values", [[], {"DATABASE_URL": "synthetic-private-value"},
    {"GROWTHOS_SECRET_REDDIT_TOKEN": None}, {"GROWTHOS_SECRET_REDDIT_TOKEN": ""}])
def test_rejects_invalid_credentials_without_echoing_values(tmp_path, values):
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_connector_secrets(path)
    assert "synthetic-private-value" not in str(exc.value)
