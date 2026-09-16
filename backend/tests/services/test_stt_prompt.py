"""stt_prompt 도메인 프롬프트 빌더 테스트"""

import pytest

from app.services import stt_prompt


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """모듈 전역 상태(캐시·거부 플래그)를 테스트마다 초기화."""
    monkeypatch.setattr(stt_prompt, "_cache", {})
    monkeypatch.setattr(stt_prompt, "_prompt_rejected", False)
    yield


class TestBuildSttPrompt:
    def test_returns_base_prompt_without_committee(self):
        prompt = stt_prompt.build_stt_prompt(None)
        assert "경기도의회" in prompt
        assert "위원장" in prompt

    def test_respects_max_chars(self, monkeypatch):
        monkeypatch.setattr(stt_prompt.settings, "stt_domain_prompt_max_chars", 60)
        prompt = stt_prompt.build_stt_prompt(None)
        assert len(prompt) <= 60

    def test_disabled_returns_empty(self, monkeypatch):
        monkeypatch.setattr(stt_prompt.settings, "stt_domain_prompt_enabled", False)
        assert stt_prompt.build_stt_prompt(None) == ""

    def test_cached_per_committee(self):
        p1 = stt_prompt.build_stt_prompt(None)
        p2 = stt_prompt.build_stt_prompt(None)
        assert p1 == p2
        assert "" in stt_prompt._cache

    def test_includes_dictionary_terms(self):
        prompt = stt_prompt.build_stt_prompt(None)
        # 기본 의회 사전(correct_text)이 힌트로 포함됨
        assert "자주 나오는 용어" in prompt


class TestPromptRejection:
    def test_mark_rejected_on_unknown_parameter_error(self):
        err = Exception("Unknown parameter: 'prompt'")
        assert stt_prompt.mark_prompt_rejected(err) is True
        assert stt_prompt.prompt_supported() is False
        assert stt_prompt.build_stt_prompt(None) == ""

    def test_unrelated_error_not_marked(self):
        err = Exception("rate limit exceeded")
        assert stt_prompt.mark_prompt_rejected(err) is False
        assert stt_prompt.prompt_supported() is True


class TestChannelHelper:
    def test_channel_helper_returns_string(self):
        # 존재하지 않는 채널이어도 base 프롬프트는 생성된다
        prompt = stt_prompt.build_stt_prompt_for_channel("ch-nonexistent")
        assert isinstance(prompt, str)
        assert "경기도의회" in prompt
