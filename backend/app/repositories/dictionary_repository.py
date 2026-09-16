"""용어사전 리포지토리 — dictionary 테이블 Supabase 접근 전담"""

from supabase import Client


class DictionaryRepository:
    def __init__(self, supabase: Client) -> None:
        self._db = supabase

    def upsert_user_correction(self, wrong: str, correct: str) -> None:
        """편집자 교정에서 수집한 단어 쌍을 user_correction 카테고리로 upsert한다."""
        self._db.table("dictionary").upsert(
            {
                "wrong_text": wrong,
                "correct_text": correct,
                "category": "user_correction",
            },
            on_conflict="wrong_text",
        ).execute()
