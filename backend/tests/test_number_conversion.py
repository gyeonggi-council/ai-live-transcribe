"""한국어 숫자 → 아라비아 숫자 변환 테스트"""

import pytest

from app.services.dictionary import (
    DictionaryService,
    convert_korean_numbers,
    _parse_sino_number,
)


class TestParseSinoNumber:
    """한자어 숫자 파싱 테스트"""

    def test_single_digit(self):
        assert _parse_sino_number("삼") == 3

    def test_tens(self):
        assert _parse_sino_number("팔십") == 80

    def test_tens_with_ones(self):
        assert _parse_sino_number("팔십오") == 85

    def test_hundreds(self):
        assert _parse_sino_number("삼백") == 300

    def test_hundreds_complex(self):
        assert _parse_sino_number("삼백오십") == 350

    def test_thousands(self):
        assert _parse_sino_number("이천삼백") == 2300

    def test_bare_ten(self):
        """'십' alone = 10"""
        assert _parse_sino_number("십") == 10

    def test_bare_hundred(self):
        """'백' alone = 100"""
        assert _parse_sino_number("백") == 100

    def test_large_man(self):
        assert _parse_sino_number("삼만") == 30000

    def test_large_eok(self):
        assert _parse_sino_number("삼천억") == 300_000_000_000

    def test_complex(self):
        assert _parse_sino_number("이십삼조") == 23_000_000_000_000


class TestConvertKoreanNumbers:
    """변환 함수 통합 테스트"""

    def test_sino_with_unit(self):
        assert convert_korean_numbers("팔십명") == "80명"

    def test_sino_complex_with_unit(self):
        assert convert_korean_numbers("삼백오십명") == "350명"

    def test_sino_large_with_unit(self):
        result = convert_korean_numbers("삼천억원")
        assert result == "3,000억원"

    def test_native_tens(self):
        assert convert_korean_numbers("여든명") == "80명"

    def test_native_compound(self):
        assert convert_korean_numbers("스물다섯명") == "25명"

    def test_sentence_context(self):
        text = "출석 의원 팔십명 중 찬성 육십오명"
        result = convert_korean_numbers(text)
        assert "80명" in result
        assert "65명" in result

    def test_no_unit_short_unchanged(self):
        """단위어 없는 2글자 이하 숫자는 변환하지 않음 (오인식 방지)"""
        assert convert_korean_numbers("이것은 삼일입니다") == "이것은 삼일입니다"

    def test_empty_string(self):
        assert convert_korean_numbers("") == ""

    def test_no_numbers(self):
        assert convert_korean_numbers("안녕하세요") == "안녕하세요"


class TestDictionaryServiceWithNumbers:
    """DictionaryService.correct() 숫자 변환 통합 테스트"""

    def test_correct_includes_number_conversion(self):
        svc = DictionaryService()
        result = svc.correct("출석 의원 팔십명입니다")
        assert "80명" in result

    def test_dictionary_and_number_conversion(self):
        from app.services.dictionary import DictionaryEntry

        svc = DictionaryService(entries=[
            DictionaryEntry("사내를 선포", "산회를 선포", "term"),
        ])
        result = svc.correct("사내를 선포합니다 출석 팔십명")
        assert "산회를 선포" in result
        assert "80명" in result
