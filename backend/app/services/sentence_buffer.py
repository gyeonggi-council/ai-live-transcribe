"""interim 자막 조각을 문장 단위로 병합하는 경량 버퍼.

WS/IO에 의존하지 않는 순수 로직. 채널별로 1개 인스턴스를 둔다.
"""

from __future__ import annotations

_SENTENCE_ENDINGS = ("다.", "요.", "까?", "죠.", "음.", "다!", "요!", "까!", ".", "?", "!")


class SentenceBuffer:
    def __init__(self, min_chars: int = 8) -> None:
        self._buf = ""
        self._min_chars = min_chars

    def push(self, fragment: str) -> str | None:
        """조각 추가. 문장이 완성되면 완성분을 반환(버퍼에서 제거), 아니면 None."""
        if not fragment:
            return None
        self._buf += fragment
        stripped = self._buf.strip()
        if len(stripped) >= self._min_chars and stripped.endswith(_SENTENCE_ENDINGS):
            out = stripped
            self._buf = ""
            return out
        return None

    def flush(self) -> str:
        """버퍼에 남은 내용을 강제로 비우고 반환."""
        out = self._buf.strip()
        self._buf = ""
        return out

    @property
    def pending(self) -> str:
        return self._buf.strip()
