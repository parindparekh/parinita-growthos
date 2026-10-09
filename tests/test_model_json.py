import pytest
from app.model_runtime import parse_model_json


@pytest.mark.parametrize("content", ['{"title":"Draft"}', '\n```json\n{"title":"Draft"}\n```\n'])
def test_model_json_object(content):
    assert parse_model_json(content) == {"title": "Draft"}


@pytest.mark.parametrize("content", ['[]', 'Here is your draft: {"title":"Draft"}', '```json\n{}\n```\nextra'])
def test_unstructured_model_output_rejected(content):
    with pytest.raises(ValueError):
        parse_model_json(content)


def test_list_is_accepted_only_for_explicit_list_contract():
    assert parse_model_json('[]', 'findings') == {'findings': []}
