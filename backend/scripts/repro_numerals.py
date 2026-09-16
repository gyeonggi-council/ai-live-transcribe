"""convert_korean_numerals 금액 손상 버그 재현."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.vod_stt_service import convert_korean_numerals as C

cases = [
    "기정액 40조 5,777억 원",
    "1조 6,222억 원 증액된 41조 6,799억 원",
    "총 8,793억 원을 감액",
    "30억 원 감액",
    "8,700억 원 중 기집행",
    "장애인복지신문 보급 2억 원",
    "1억 5천만 원",
    "1,424만 도민",
    "제390회",
    "제1항",
    "삼백팔십칠",
    "오천칠백칠십칠억",
]
for c in cases:
    print(f"{c!r}\n  -> {C(c)!r}\n")
