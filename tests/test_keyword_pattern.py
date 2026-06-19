import pytest

from vic3_state_merger.state_merger import (
    _build_keyword_pattern,
    _keyword_remove,
    _keyword_replace,
)


def _do_replace(text, merge_dict):
    lookup, pattern = _build_keyword_pattern(merge_dict)
    assert pattern is not None
    return pattern.sub(lambda m: _keyword_replace(m, lookup, text), text)


def _do_remove(text, merge_dict):
    lookup, pattern = _build_keyword_pattern(merge_dict)
    assert pattern is not None
    return pattern.sub(lambda m: _keyword_remove(m, lookup, text), text)


@pytest.fixture
def merge_dict():
    return {
        "STATE_MASSACHUSETTS": ["STATE_MAINE", "STATE_VERMONT"],
        "STATE_SCOTLAND": ["STATE_HIGHLANDS"],
        "STATE_SOUTH_CAMEROON": ["STATE_NORTH_CAMEROON"],
    }


class TestKeywordReplace:
    def test_replaces_standalone_state_id(self, merge_dict):
        result = _do_replace("STATE_MAINE = { }", merge_dict)
        assert result == "STATE_MASSACHUSETTS = { }"

    def test_replaces_in_lowercase_compound(self, merge_dict):
        result = _do_replace(
            "STATE_HIGHLANDS_state_name_assign = yes", merge_dict
        )
        assert result == "STATE_SCOTLAND_state_name_assign = yes"

    def test_replaces_multi_word_state_in_prefixed_compound(self, merge_dict):
        result = _do_replace(
            "HUB_NAME_STATE_NORTH_CAMEROON_city_german = yes", merge_dict
        )
        assert result == "HUB_NAME_STATE_SOUTH_CAMEROON_city_german = yes"

    def test_does_not_replace_uppercase_compound_suffix(self, merge_dict):
        result = _do_replace("STATE_MAINE_ANJOU", merge_dict)
        assert result == "STATE_MAINE_ANJOU"

    def test_does_not_replace_uppercase_compound_prefix(self, merge_dict):
        merge_dict_with_anjou = {
            "STATE_MASSACHUSETTS": ["STATE_ANJOU"],
        }
        result = _do_replace("STATE_MAINE_ANJOU", merge_dict_with_anjou)
        assert result == "STATE_MAINE_ANJOU"

    def test_replaces_in_mixed_case_compound(self, merge_dict):
        result = _do_replace(
            "STATE_HIGHLANDS_city_data = 1", merge_dict
        )
        assert result == "STATE_SCOTLAND_city_data = 1"

    def test_multiple_replacements_in_text(self, merge_dict):
        text = (
            "STATE_MAINE = 1\n"
            "STATE_HIGHLANDS_state_name_assign = 2\n"
            "STATE_MAINE_ANJOU = 3\n"
            "HUB_NAME_STATE_NORTH_CAMEROON_city_german = 4"
        )
        result = _do_replace(text, merge_dict)
        assert "STATE_MASSACHUSETTS = 1" in result
        assert "STATE_SCOTLAND_state_name_assign = 2" in result
        assert "STATE_MAINE_ANJOU = 3" in result
        assert "HUB_NAME_STATE_SOUTH_CAMEROON_city_german = 4" in result


class TestKeywordRemove:
    def test_removes_standalone_state_id(self, merge_dict):
        result = _do_remove("STATE_NORTH_CAMEROON = { }", merge_dict)
        assert result == " = { }"

    def test_does_not_remove_uppercase_compound_suffix(self, merge_dict):
        result = _do_remove("STATE_MAINE_ANJOU", merge_dict)
        assert result == "STATE_MAINE_ANJOU"

    def test_does_not_remove_uppercase_compound_prefix(self, merge_dict):
        merge_dict_with_anjou = {
            "STATE_MASSACHUSETTS": ["STATE_ANJOU"],
        }
        result = _do_remove("STATE_MAINE_ANJOU", merge_dict_with_anjou)
        assert result == "STATE_MAINE_ANJOU"


class TestBuildKeywordPattern:
    def test_empty_merge_dict(self):
        lookup, pattern = _build_keyword_pattern({})
        assert lookup == {}
        assert pattern is None
