"""이름 퍼지 매칭(services/name_match, 2026-09-15)."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "name_match", Path(__file__).resolve().parents[2] / "app" / "services" / "name_match.py")
nm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nm)

ROSTER = ["장한별", "김태희", "김회철", "문승호", "신미숙", "오남석", "오지훈", "유경현", "이병숙", "이오수", "이자형", "장민수", "전자영"]


def test_exact_and_typo():
    assert nm.resolve_person("이자형", ROSTER) == "이자형"
    assert nm.resolve_person("이자영", ROSTER) == "이자형"  # 한 글자 오타 — 전자영(0.667)보다 이자형(0.767)
    assert nm.resolve_person("유경헌", ROSTER) == "유경현"


def test_unknown_or_far_names_are_none():
    assert nm.resolve_person("홍길동", ROSTER) is None
    assert nm.resolve_person("", ROSTER) is None
    assert nm.resolve_person("이자형", []) is None


def test_tie_prefers_meeting_speakers_else_none():
    cands = ["이자형", "이자영"]
    assert nm.resolve_person("이자수", cands) is None  # 둘 다 0.767 동점 — 아무나 고르지 않는다
    assert nm.resolve_person("이자수", cands, prefer=["이자영"]) == "이자영"
    # 모음만 다른 오인식은 자모 점수가 가른다(김해철 → 김회철 0.925, 김철환 0.767)
    assert nm.resolve_person("김해철", ["김회철", "김철환"]) == "김회철"


def test_jamo_catches_vowel_errors():
    assert nm.jamo("이자형") == "ㅇㅣㅈㅏㅎㅕㅇ"
    assert nm.resolve_person("강송상", ["강성삼", "고은정"]) == "강성삼"
