"""VOD STT 처리 서비스 (OpenAI gpt-4o-transcribe-diarize 배치).

KMS에서 MP4를 다운로드 → ffmpeg로 오디오를 mp3 청크(≤25MB)로 분할 → 각 청크를
OpenAI 배치 전사(diarized_json)로 처리 → 타임스탬프 오프셋 보정 후 결합 → DB 저장.

Deepgram을 제거하고 라이브 경로(diarize_service)와 동일한 OpenAI 배치 패턴을 재사용한다.
OpenAI 전사 API는 25MB 파일 한도 + .ts/대용량 미지원이라, ffmpeg로 mp3 청크 분할이 필요하다
(Docker/로컬/배포 환경에 ffmpeg 포함).
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from openai import AsyncOpenAI
from supabase import Client

from app.core.config import settings
from app.core.proc_priority import LOW_PRIORITY
from app.services.dictionary import get_default_dictionary
from app.services.name_corrector import correct_member_names, correct_staff_names
from app.services.numeral_normalizer import llm_fix_numerals, normalize_amount_runs
from app.services.roster_loader import load_committee_with_roles
from app.services.staff_roster_service import load_staff_roster, staff_names
from app.services.kms_vod_resolver import normalize_vod_download_url
from app.services.vod_processor import VodDownloadError

logger = logging.getLogger(__name__)

# mp3 청크 분할 — 균일 분할(2026-06-16 재수정, 자막 누락 사고 후 원복).
# ★무음경계 가변 청킹(이전 시도)의 사고: 의회 음성은 무음(-30dB,0.4s)이 드물어
#   컷 로직이 과대 청크(>600s)를 만들었고, 그런 큰 청크가 전사 실패하면 5~11분짜리
#   거대 공백이 생겨 회의 자막의 ~40%가 통째로 누락됐다(개의·보고·답변이 사라짐).
# 해법: 균일 분할로 원복. 모든 구간이 작은 청크 하나에 정확히 들어가 누락 위험이 작고,
#   설사 한 청크가 실패해도 공백이 청크 크기(작음)로 한정된다. 커버리지 > 문맥 최적화.
#   오프셋은 실제 길이(ffprobe) 누적 — 균일 청크에선 i×길이와 동일하지만 마지막
#   짧은 청크까지 정확. (연회비류 문맥 오인식은 사용자 합의대로 현행 유지)
_TARGET_CHUNK_SECONDS = 180   # 균일 청크 길이(초). 작아서 전사 실패해도 공백이 작게 한정.
# OpenAI 전사 API 청크당 타임아웃(초).
_OPENAI_TIMEOUT = 900.0
# 청크 동시 전사 수(전체 대기시간 단축). diarize 동시호출 과다 시 rate limit → 보수적으로.
_CHUNK_CONCURRENCY = 3
# 청크 전사 실패 시 재시도 횟수(지수 백오프).
_CHUNK_RETRIES = 2


def _speaker_label(raw) -> str | None:
    """diarize speaker("A","B",…) → "화자 N"."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if len(s) == 1 and "A" <= s.upper() <= "Z":
        return f"화자 {ord(s.upper()) - ord('A') + 1}"
    return s


def _attr(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ── 추임새/백채널 토큰 필터 ─────────────────────────────────────────────
# diarize 모델이 한국어 회의에서 짧은 호흡/맞장구를 영어 간투사("Mm.","Yeah.","Oh.")로
# 내보내는 노이즈를 제거한다. 의미 있는 짧은 한국어 답변("예","네")은 보존한다.
_FILLER_SET = {
    "mm", "mmm", "hmm", "hm", "hmmm", "uh", "uhh", "um", "umm", "oh", "ohh",
    "ah", "ahh", "eh", "huh", "yeah", "yep", "yup", "mhm", "uhhuh", "ya", "wow",
    "음", "흠", "으음", "음음", "어어",
}
_FILLER_RE = re.compile(
    r"^(?:m+|h+m*|hm+|u+h*|u+m+|a+h*|o+h*|e+h*|y+e+a+h+|mhm+|uh-?huh)$"
)


def _is_filler(text: str) -> bool:
    """추임새/백채널 토큰이면 True (한국어 자막 노이즈 제거용)."""
    if not text:
        return True
    cleaned = re.sub(r"[\s.,!?~…\-’'\"()]+", "", text).lower()
    if not cleaned:
        return True
    has_hangul = any("가" <= c <= "힣" for c in cleaned)
    if not has_hangul and (cleaned in _FILLER_SET or _FILLER_RE.match(cleaned)):
        return True
    # 순수 한글 hum 토큰(예/네 등 의미 있는 답변은 제외)
    if cleaned in _FILLER_SET:
        return True
    return False


def _is_hallucination(text: str) -> bool:
    """STT 환각/반복 루프 세그먼트면 True (한국어 회의 자막용).

    diarize 모델이 긴 청크의 모호한 구간에서 빠지는 전형적 쓰레기:
    ① 영어 문장 환각 ("the positivity is seventy percent are not go...")
    ② 같은 단어/구 무한 반복 ("a bit of a bit of a bit of...")
    한국어 회의에서 명백한 환각만 통째로 버린다 (영어 약어·고유명사는 통과).
    """
    t = (text or "").strip()
    if not t:
        return False
    han = sum(1 for c in t if "가" <= c <= "힣")
    lat = sum(1 for c in t if "a" <= c.lower() <= "z")
    words = t.split()
    # ⓪ 짧은 영어 단독 세그먼트 (한글 0, 영어 위주, ≤6단어) — diarize가
    #    '네/그래요/알았어요' 같은 짧은 한국어 응답을 'yeah/okay/alright'로
    #    환각하는 패턴. 회의 본문에 영어 단독 발언은 거의 없으므로 제거.
    if han == 0 and lat >= 2 and len(words) <= 6:
        return True
    if len(t) < 8:
        return False
    # ① 영어 환각: 영어가 한글의 2배 이상 + 절대량 큼
    if lat >= 20 and lat > han * 2:
        return True
    # ② 반복 루프: 고유 단어 비율이 매우 낮음
    if len(words) >= 12:
        uniq = len(set(w.lower() for w in words))
        if uniq / len(words) < 0.30:
            return True
    # ③ 같은 2~3단어 구가 4회 이상 반복
    if len(words) >= 9:
        from collections import Counter

        for size in (2, 3):
            chunks = [
                tuple(w.lower() for w in words[i : i + size])
                for i in range(0, len(words) - size + 1)
            ]
            if chunks and Counter(chunks).most_common(1)[0][1] >= 4:
                return True
    return False


# 한국어 발언 앞/뒤에 환각으로 붙는 영어 추임새 (화이트리스트 — 안전)
_ENG_FILLER_WORDS = (
    r"yeah|yes|no|ok|okay|alright|all\s*right|right|uh+|um+|mm+|hmm+|"
    r"so|and|well|oh|got\s*it|i\s*see|mm-?hmm"
)
_ENG_TAIL_RE = re.compile(
    rf"[\s,]+(?:(?:{_ENG_FILLER_WORDS})[\s,.!?]*)+$", re.IGNORECASE
)
_ENG_HEAD_RE = re.compile(
    rf"^(?:(?:{_ENG_FILLER_WORDS})[\s,.!?]+)+", re.IGNORECASE
)


def _strip_english_tail(text: str) -> str:
    """한국어 문장 앞/뒤에 환각으로 붙은 영어 추임새를 제거.

    '네, yeah.' → '네.', 'Yeah, 안녕하십니까?' → '안녕하십니까?',
    'yeah yeah 그 상황' → '그 상황'. diarize가 한국어 발언 앞뒤에 영어
    추임새를 환각하는 패턴. 한글이 주된 문장에서 화이트리스트 단어만 떼어내
    본문은 보존한다.
    """
    t = text.strip()
    if sum(1 for c in t if "가" <= c <= "힣") < 1:
        return t  # 한글이 전혀 없으면 _is_hallucination이 처리
    cleaned = _ENG_HEAD_RE.sub("", t).strip()
    cleaned = _ENG_TAIL_RE.sub("", cleaned).strip().rstrip(",")
    # 제거 후에도 한글이 남아 의미가 보존될 때만 적용
    if cleaned and cleaned != t and any("가" <= c <= "힣" for c in cleaned):
        if not cleaned.endswith((".", "?", "!", "다", "요", "까", "죠")):
            cleaned += "."
        return cleaned
    return t


def split_sentences_with_timestamps(
    text: str, start: float, end: float
) -> list[tuple[str, float, float]]:
    """긴 세그먼트 텍스트를 문장으로 나누고 [start,end]를 글자수 비례 배분.

    한 화자의 긴 발언이 수십 문장의 한 덩어리로 뭉치지 않도록, 문장 경계로
    쪼개 1~2문장 단위 자막을 만든다 (사용자 요구: 문장 1~2개로 분할).
    """
    # ① 격식체 서술어 뒤 마침표 삽입 → ② 이미 있는 문장부호(. ? !) 뒤에서도 분리.
    #    (소수점·약어처럼 부호 뒤 공백이 없으면 나누지 않아 '11.5%'는 안전)
    broken = add_sentence_breaks(text)
    broken = re.sub(r"([.?!])\s+", r"\1\n", broken)
    lines = [ln.strip() for ln in broken.split("\n") if ln.strip()]
    if len(lines) <= 1:
        return [(text.strip(), round(start, 2), round(end, 2))] if text.strip() else []
    span = max(0.0, end - start)
    total_chars = sum(len(ln) for ln in lines) or 1
    out: list[tuple[str, float, float]] = []
    cursor = start
    for i, ln in enumerate(lines):
        dur = span * len(ln) / total_chars
        seg_end = end if i == len(lines) - 1 else cursor + dur
        out.append((ln, round(cursor, 2), round(seg_end, 2)))
        cursor = seg_end
    return out


# ============================================================================
# Task Status (인메모리)
# ============================================================================


@dataclass
class SttTaskStatus:
    """STT 태스크 상태"""

    task_id: str
    meeting_id: str
    status: str = "pending"  # pending | running | completed | failed
    progress: float = 0.0  # 0.0 ~ 1.0
    message: str = ""
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# 인메모리 태스크 저장소: meeting_id → SttTaskStatus
_tasks: dict[str, SttTaskStatus] = {}


def get_task_by_meeting(meeting_id: str) -> SttTaskStatus | None:
    return _tasks.get(meeting_id)


def get_task_by_id(task_id: str) -> SttTaskStatus | None:
    for task in _tasks.values():
        if task.task_id == task_id:
            return task
    return None


def is_processing(meeting_id: str) -> bool:
    task = _tasks.get(meeting_id)
    return task is not None and task.status in ("pending", "running")


def reset_orphaned_processing(supabase) -> int:
    """서버 기동 시 고아 'processing' 회의를 'ended'로 복구한다.

    STT 태스크는 인메모리라 재시작하면 사라지는데 meetings.status='processing'은
    DB에 남는다 — 그대로 두면 화면이 영원히 'AI 자막 생성 중'으로 보이고
    1회-처리 가드(409)에도 막힌다. 기동 직후엔 인메모리 태스크가 없으므로
    processing 상태는 전부 고아가 확실하다.
    """
    try:
        rows = (
            supabase.table("meetings")
            .update({"status": "ended"})
            .eq("status", "processing")
            .execute()
            .data
            or []
        )
        if rows:
            logger.info("고아 'processing' 회의 %d건을 ended로 복구", len(rows))
        return len(rows)
    except Exception as e:
        logger.warning("고아 processing 복구 실패: %s", e)
        return 0


# ============================================================================
# 한글 숫자 → 아라비아 숫자 변환
# ============================================================================

_KR_DIGITS = {'일': 1, '이': 2, '삼': 3, '사': 4, '오': 5, '육': 6, '칠': 7, '팔': 8, '구': 9}
_KR_UNITS = {'십': 10, '백': 100, '천': 1000}
_KR_BIG_UNITS = {'만': 10000, '억': 100000000}
_KR_NUM_CHARS = '일이삼사오육칠팔구십백천만억'
# 실제 숫자 글자(일~구). 단위 글자(십백천만억/조)는 한글 숫자 글자이기도 해서,
# 아라비아 숫자 뒤의 단독 단위("5,777억", "30억")를 숫자로 잘못 변환하는 원인이 된다
# (예: "30억"→"30"+"억"="100000000"→"30100000000"). 단위만 있고 일~구 숫자가 없는
# 토큰은 화자가 말한 자릿수 단어이므로 변환하지 않고 그대로 둔다.
_KR_DIGIT_CHARS = '일이삼사오육칠팔구'


def _has_kr_digit(s: str) -> bool:
    """문자열에 실제 한글 숫자(일~구)가 하나라도 있는지."""
    return any(c in _KR_DIGIT_CHARS for c in s)


def _korean_num_to_int(s: str) -> int | None:
    """한글 숫자 문자열을 정수로 변환 (예: '삼백팔십칠' → 387)"""
    chars = s.replace(' ', '')
    if not chars or not all(c in _KR_NUM_CHARS for c in chars):
        return None

    big_result = 0
    result = 0
    current = 0

    for ch in chars:
        if ch in _KR_DIGITS:
            current = _KR_DIGITS[ch]
        elif ch in _KR_UNITS:
            if current == 0:
                current = 1
            result += current * _KR_UNITS[ch]
            current = 0
        elif ch in _KR_BIG_UNITS:
            result += current
            current = 0
            if result == 0:
                result = 1
            big_result += result * _KR_BIG_UNITS[ch]
            result = 0

    return big_result + result + current or None


def convert_korean_numerals(text: str) -> str:
    """텍스트 내 한글 숫자를 아라비아 숫자로 변환 (제X회/X명/X억 등 + 단위 포함 다중글자)."""
    def _replace_ctx(m: re.Match) -> str:
        prefix = m.group(1).replace(' ', '')
        num_str = m.group(2)
        suffix = m.group(3).replace(' ', '')
        val = _korean_num_to_int(num_str)
        if val is not None:
            return f"{prefix}{val}{suffix}"
        return m.group(0)

    result = re.sub(
        rf'(제\s*)([{_KR_NUM_CHARS}](?:\s*[{_KR_NUM_CHARS}])*)(\s*[회차호])',
        _replace_ctx, text
    )

    def _replace_unit(m: re.Match) -> str:
        num_str = m.group(1)
        unit = m.group(2)
        # 일~구 숫자가 없는 단위-only 토큰("억","천만" 등)은 변환 금지 — 금액 손상 방지
        if not _has_kr_digit(num_str):
            return m.group(0)
        val = _korean_num_to_int(num_str)
        if val is not None:
            return f"{val}{unit}"
        return m.group(0)

    result = re.sub(
        rf'([{_KR_NUM_CHARS}](?:\s*[{_KR_NUM_CHARS}])*)(\s*[억원건명개조])',
        _replace_unit, result
    )

    def _replace_multi(m: re.Match) -> str:
        raw = m.group(0)
        stripped = raw.replace(' ', '')
        if not any(c in stripped for c in '십백천만억'):
            return raw
        # 일~구 숫자가 없는 단위-only 토큰("천만","백만","억")은 변환 금지 — 금액 손상 방지
        if not _has_kr_digit(stripped):
            return raw
        val = _korean_num_to_int(stripped)
        if val is not None:
            return str(val)
        return raw

    result = re.sub(
        rf'[{_KR_NUM_CHARS}](?:\s*[{_KR_NUM_CHARS}]){{1,}}',
        _replace_multi, result
    )

    return result


# ============================================================================
# 서술어 기준 문장 분리 + 마침표 삽입
# ============================================================================

_SENTENCE_ENDINGS = re.compile(
    r'(합니다|입니다|습니다|됩니다|겠습니다|하겠습니다|드리겠습니다|있습니다|없습니다'
    r'|봅니다|줍니다|옵니다|갑니다|납니다|랍니다|답니다|였습니다|었습니다'
    r'|하십시오|하시오|바랍니다|시기 바랍니다'
    r'|니까|십니까|습니까|합니까|됩니까|겠습니까'
    r'|해요|하세요|되세요|드려요|할게요|할까요'
    r'|하였으며|하였고|되었으며|되었고'
    r'|것이며|것이고|바이며'
    r'|주세요|드립니다|올리겠습니다'
    r')(?=\s)'
)


def add_sentence_breaks(text: str) -> str:
    """서술어 뒤에 마침표 추가 + 줄바꿈으로 문장 분리."""
    if not text:
        return text

    result = _SENTENCE_ENDINGS.sub(r'\1.\n', text)
    result = result.rstrip()
    if result and not result.endswith(('.', '?', '!')):
        last_line = result.split('\n')[-1].rstrip()
        for ending in ['합니다', '입니다', '습니다', '됩니다', '겠습니다', '바랍니다',
                       '습니까', '합니까', '됩니까', '하세요', '주세요', '드립니다']:
            if last_line.endswith(ending):
                result = result + '.'
                break

    result = result.replace('..', '.')
    result = re.sub(r'\n\s+', '\n', result)
    return result


# ============================================================================
# VOD STT Service
# ============================================================================


class VodSttService:
    """VOD STT 처리 서비스 (OpenAI gpt-4o-transcribe-diarize 배치).

    MP4 다운로드 → ffmpeg로 mp3 청크 분할 → OpenAI 배치 전사(화자 구분) → 결합 → DB 저장.
    """

    @staticmethod
    def _load_live_subtitles(meeting_id: str) -> list[dict]:
        """이 회의의 실시간(kind='live') 자막을 로드. 없으면 빈 리스트.

        라이브 자막은 live_corrector(gpt-5.4-mini) 사후교정을 거쳐 용어/이름이
        VOD 단독 전사보다 정확한 경우가 많다. VOD 재전사 시 같은 시간대 라이브
        텍스트를 prompt 힌트로 주입해 동음이의 오인식(연회비→연예비 등)을 줄인다.
        VOD 전용 회의(라이브 없음)는 빈 리스트 → 기존 동작 그대로(무해).
        """
        try:
            from app.core.database import get_supabase_client

            rows = (
                get_supabase_client()
                .table("subtitles")
                .select("start_time,end_time,text")
                .eq("meeting_id", meeting_id)
                .eq("kind", "live")
                .order("start_time")
                .execute()
                .data
                or []
            )
            return [r for r in rows if (r.get("text") or "").strip()]
        except Exception as e:
            logger.debug("라이브 자막 로드 스킵: %s", e)
            return []

    @staticmethod
    def _chunk_live_context(
        live_subs: list[dict], start: float, end: float, max_chars: int = 500
    ) -> str:
        """청크 시간창[start,end]과 겹치는 라이브 자막 텍스트를 모아 prompt 힌트로 반환.

        시간 정렬(겹침)로 '그 구간에 실제로 나온' 라이브 텍스트만 주입하므로
        전역 블롭보다 관련성이 높고 토큰도 절약된다. 비면 빈 문자열.
        """
        if not live_subs:
            return ""
        picked: list[str] = []
        total = 0
        for s in live_subs:
            ss = float(s.get("start_time") or 0)
            se = float(s.get("end_time") or ss)
            if se < start or ss > end:  # 시간창 밖
                continue
            t = (s.get("text") or "").strip()
            if not t:
                continue
            if total + len(t) > max_chars:
                break
            picked.append(t)
            total += len(t)
        if not picked:
            return ""
        return "\n이 구간의 실시간 자막(참고용 — 표기를 우선 따르세요): " + " ".join(picked)

    @staticmethod
    def _load_meeting_committee(supabase: Client, meeting_id: str) -> str | None:
        """회의의 위원회명. 미상/조회 실패 시 None (fail-soft)."""
        try:
            m = (
                supabase.table("meetings").select("committee")
                .eq("id", meeting_id).limit(1).execute()
            )
            return m.data[0].get("committee") if m.data else None
        except Exception:
            return None

    def _load_committee_roster(self, supabase: Client, meeting_id: str) -> list[str]:
        """회의의 위원회 명부(위원 이름) 로드. 실패 시 빈 리스트.

        councilors의 위원회는 스칼라 'committee'가 아니라 JSONB 배열 'committees'다.
        라이브 경로와 동일한 단일 진실 소스(get_by_committee)를 재사용해 두 경로가
        같은 명부를 보게 한다(과거: VOD는 .eq("committee")로 빈 명부 → C-2 no-op).
        """
        try:
            m = (
                supabase.table("meetings").select("committee")
                .eq("id", meeting_id).limit(1).execute()
            )
            committee = m.data[0].get("committee") if m.data else None
            if not committee:
                return []
            from app.services.councilor_sync import CouncilorSyncService
            roster = CouncilorSyncService(supabase).get_by_committee(committee)
            return [r["name"] for r in roster if r.get("name")]
        except Exception as e:
            logger.warning("위원회 명부 로드 실패: %s", e)
            return []

    @staticmethod
    def _load_committee_with_roles(supabase, meeting_id: str):
        """회의의 (위원회명, [{name, role}]) 반환 — 텍스트 화자귀속용.

        명부 로드는 roster_loader.load_committee_with_roles(단일 진실 소스:
        committee_rosters.json 우선 → councilors DB 폴백)에 위임한다.
        위원회 미상이면 (None, []).
        """
        committee = None
        try:
            m = (
                supabase.table("meetings").select("committee")
                .eq("id", meeting_id).limit(1).execute()
            )
            committee = m.data[0].get("committee") if m.data else None
        except Exception:
            committee = None
        if not committee:
            return None, []
        return committee, load_committee_with_roles(supabase, committee)

    async def process(
        self,
        meeting_id: str,
        vod_url: str,
        supabase: Client,
    ) -> None:
        """VOD STT 전체 파이프라인 실행.

        1. KMS에서 MP4 다운로드 → 임시 파일
        2. ffmpeg로 mp3 청크 분할
        3. 각 청크 OpenAI 전사(diarized_json) → 타임스탬프 결합
        4. 자막 DB 저장
        """
        task_id = str(uuid.uuid4())
        task = SttTaskStatus(
            task_id=task_id, meeting_id=meeting_id, status="running", message="처리 시작",
        )
        _tasks[meeting_id] = task

        # KMS HLS(.m3u8) URL이면 직접 MP4로 정규화 (HLS 재생목록은 152바이트라 다운로드 실패함)
        vod_url = normalize_vod_download_url(vod_url)

        mp4_path: Path | None = None
        try:
            self._update_task(task, 0.05, "회의 상태 업데이트 중")
            await self._update_meeting_status(supabase, meeting_id, "processing")

            # 1. 다운로드 (OpenAI는 URL 입력 미지원 → 직접 받아야 함)
            self._update_task(task, 0.08, "VOD 다운로드 시작")
            mp4_path = await self._download_to_file(vod_url, task)
            logger.info("VOD 다운로드 완료: %.0f MB", mp4_path.stat().st_size / (1024 * 1024))

            # 2~3. ffmpeg 청크 분할 + OpenAI 전사
            # DB 용어사전 병합 — /admin/dictionary 교정 쌍이 VOD 자막에도 적용
            dictionary = get_default_dictionary()
            try:
                await asyncio.to_thread(dictionary.load_from_db, supabase)
            except Exception as de:
                logger.debug("DB 사전 로드 스킵: %s", de)
            all_subtitles, duration = await self._transcribe_openai(
                meeting_id, mp4_path, task, dictionary
            )
            logger.info("%d개 자막 생성", len(all_subtitles))

            # 위원 이름 명부 교정 (그 위원회 명부 밖 이름은 안 건드림)
            roster_names = self._load_committee_roster(supabase, meeting_id)
            if roster_names:
                for s in all_subtitles:
                    s["text"] = correct_member_names(s.get("text", ""), roster_names)

            # 집행부 공무원 이름 교정 — staff_roster(속기록 출석명단) 명부 기반.
            # staff_entries(name/title/department/full_title)는 이후 화자귀속
            # 단계가 재사용한다. 명부 없음/테이블 미존재는 fail-soft(빈 리스트).
            committee = self._load_meeting_committee(supabase, meeting_id)
            staff_entries: list[dict] = (
                load_staff_roster(supabase, committee) if committee else []
            )
            if staff_entries:
                staff_name_list = staff_names(staff_entries)
                for s in all_subtitles:
                    s["text"] = correct_staff_names(s.get("text", ""), staff_name_list)

            # 예산/큰숫자 LLM 교정 — 의심 라인(무단위 긴 숫자열 등)만 골라 배치 1회
            # 재구성. DB insert 전이라 교정 결과가 그대로 저장된다 (fail-soft).
            if settings.vod_numeral_llm_fix and settings.openai_api_key and all_subtitles:
                try:
                    self._update_task(task, 0.92, "예산/숫자 표기 교정 중")
                    fixed = await llm_fix_numerals(
                        all_subtitles,
                        AsyncOpenAI(api_key=settings.openai_api_key),
                        settings.openai_model,
                    )
                    if fixed:
                        logger.info("예산/숫자 LLM 교정: %d개 자막 수정", fixed)
                except Exception as e:
                    logger.warning("예산/숫자 LLM 교정 실패(무시): %s", e)

            # 텍스트 기반 화자귀속 — 오디오 재처리 없이 명부+단서로 실명 화자 부여
            # (오디오 diarize 2-패스 대신 기본. 이름교정 후라 호명 단서가 더 정확.)
            roster: list[dict] = []
            if settings.vod_text_speaker_attribution and all_subtitles:
                try:
                    committee, roster = self._load_committee_with_roles(supabase, meeting_id)
                    if roster:
                        from app.services.text_speaker_service import attribute_speakers

                        self._update_task(task, 0.93, "화자 구분 중 (텍스트 분석)")
                        # staff_entries(출석 공무원 명부) 전달 — 집행부 답변을
                        # '실명+직책'(예: 배성호 건설국장)으로 귀속 (직책 혼동 감소)
                        labeled = await attribute_speakers(
                            all_subtitles, roster, committee, staff=staff_entries
                        )
                        logger.info("텍스트 화자귀속: %d/%d 자막에 화자 부여", labeled, len(all_subtitles))
                except Exception as e:
                    logger.warning("텍스트 화자귀속 실패(무시): %s", e)

            # 음성 화자 융합 — 텍스트 귀속 결과를 창별 화자 임베딩으로 교정 (2026-09-05).
            # ★mp4 를 지우기 전에 돌려야 한다(오디오를 여기서 다시 뽑는다). 실패는 텍스트 결과 유지.
            if settings.vod_voice_speaker_fusion and all_subtitles and roster:
                try:
                    from app.services.speaker_voice_fusion import fuse_voice_speakers

                    self._update_task(task, 0.94, "화자 구분 보정 중 (음성 비교)")
                    fstats = await fuse_voice_speakers(all_subtitles, roster, mp4_path=mp4_path)
                    logger.info(
                        "음성 화자 융합(%s): %s", meeting_id,
                        {k: v for k, v in fstats.items() if k not in ("anchors", "reliable")},
                    )
                except Exception as e:
                    logger.warning("음성 화자 융합 실패(텍스트 결과 유지): %s", e)

            mp4_path.unlink(missing_ok=True)
            mp4_path = None

            # 4. DB 저장 — 라이브(초안) 자막을 VOD 고품질 자막으로 '교체'한다.
            # 전사 성공이 확정된 뒤에만 기존 AI 자막을 삭제 (실패 시 기존 보존).
            # ★실시간 자막(kind='live')은 보존 — AI 자막(kind='ai')만 교체해
            #   회의록에서 실시간↔AI 비교가 가능하게 한다.
            self._update_task(task, 0.95, "자막 저장 중")
            if all_subtitles:
                try:
                    supabase.table("subtitles").delete().eq(
                        "meeting_id", meeting_id
                    ).eq("kind", "ai").execute()
                except Exception as de:
                    logger.warning("기존 AI 자막 삭제 실패(중복 가능): %s", de)
                await self._insert_subtitles(supabase, all_subtitles)

            # 자막 생성 성공 시 워크플로우 단계 'ai'로 승격 → /vod 배지가 "AI 자막"으로 정확히 표시
            # (이미 속기사 검토중/확정이면 보존). 자막이 0개면 단계 변경 안 함.
            promote = (
                "ai"
                if all_subtitles and self._should_promote_to_ai(supabase, meeting_id)
                else None
            )
            await self._update_meeting_status(
                supabase, meeting_id, "ended",
                duration_seconds=int(duration) if duration else None,
                subtitle_stage=promote,
            )

            # AI 자막 생성 완료 → 메타데이터 구조화 단계: 자막(원천데이터)에서 안건/
            # 의사일정을 추출·저장해 회의록(hwpx)·RAG·검색이 바로 쓰게 한다.
            # 멱등(사람 입력 안건 보존) + 비치명적(추출 실패해도 자막 생성은 성공으로 마감).
            if all_subtitles:
                self._update_task(task, 0.98, "안건/의사일정 메타데이터 추출 중")
                try:
                    from app.services.agenda_draft_service import ensure_agendas

                    agendas = await ensure_agendas(supabase, meeting_id)
                    logger.info("안건 메타데이터 구조화 완료: %d건", len(agendas))
                except Exception as ae:
                    logger.warning("안건 자동 추출 실패(자막 생성은 완료 처리): %s", ae)

            # 라이브 감지 요구자료 시각 재정렬 — 라이브 STT 시계 → VOD(AI) 자막 시계.
            # (라이브·VOD 시계 오프셋은 정회 편집 등으로 가변이라 항목별 텍스트 매칭)
            if all_subtitles:
                self._update_task(task, 0.99, "요구자료 발언 시각 재정렬 중")
                try:
                    from app.services.material_request_anchor import reanchor_live_requests

                    stats = await reanchor_live_requests(supabase, meeting_id)
                    if stats["total"]:
                        logger.info(
                            "요구자료 재앵커 완료: %s",
                            {k: v for k, v in stats.items() if k != "plans"},
                        )
                except Exception as me:
                    logger.warning("요구자료 재앵커 실패(자막 생성은 완료 처리): %s", me)

            task.status = "completed"
            task.progress = 1.0
            task.message = f"완료 - {len(all_subtitles)}개 자막 생성"
            logger.info("VOD STT 완료: %d개 자막", len(all_subtitles))

        except Exception as e:
            logger.exception("VOD STT 처리 실패: %s", e)
            task.status = "failed"
            task.error = str(e) or type(e).__name__
            task.message = "처리 실패"
            try:
                await self._update_meeting_status(supabase, meeting_id, "ended")
            except Exception:
                pass
        finally:
            if mp4_path and mp4_path.exists():
                mp4_path.unlink(missing_ok=True)

    # ─── OpenAI 배치 전사 ───

    async def _transcribe_openai(
        self,
        meeting_id: str,
        mp4_path: Path,
        task: SttTaskStatus,
        dictionary=None,
    ) -> tuple[list[dict], float]:
        """ffmpeg로 mp3 청크 분할 후 각 청크를 OpenAI 배치 전사하여 자막으로 결합.

        청크는 bounded concurrency로 병렬 전사하며, 청크별 재시도 + 실패 표면화로
        '일부 청크 실패가 조용히 누락되는' 문제를 방지한다(과거: 40분 청크 타임아웃 → 앞부분 통째 누락).
        """
        if not settings.openai_api_key:
            raise Exception("OPENAI_API_KEY가 설정되지 않았습니다.")

        self._update_task(task, 0.2, "오디오 추출/분할 중 (ffmpeg)")
        chunks = await self._extract_audio_chunks(mp4_path)
        if not chunks:
            raise Exception("ffmpeg 오디오 추출 실패 (청크 0개)")

        # 회의별 글로서리 prompt (의원명+용어사전+의안명) — 실시간과 동일하게
        # 전사 모델에 한국어 컨텍스트를 주입해 영어 환각·용어 오인식을 억제한다.
        glossary_prompt = ""
        try:
            from app.services.glossary_service import (
                format_glossary_prompt,
                load_meeting_glossary,
            )
            from app.core.database import get_supabase_client

            terms = await asyncio.to_thread(
                load_meeting_glossary, get_supabase_client(), meeting_id
            )
            # ★캡 1400자(2026-06-16): 900자에선 의원명+절차+기관에서 잘려 부서명
            #   (첨단모빌리티산업과 등 뒤쪽 항목)이 prompt에 안 들어갔다. VOD는
            #   청크 1회씩만 전송하므로 캡을 늘려도 비용 증가는 미미(~+50토큰/청크).
            glossary_prompt = format_glossary_prompt(terms, max_terms=250, max_chars=1400)
        except Exception as ge:
            logger.debug("VOD 글로서리 생성 스킵: %s", ge)

        # 라이브(실시간) 자막 1회 로드 — 청크별 시간겹침으로 prompt 힌트 주입(교차참조).
        # VOD 전용 회의는 빈 리스트라 기존 동작 그대로(무해).
        live_subs = await asyncio.to_thread(self._load_live_subtitles, meeting_id)
        if live_subs:
            logger.info("라이브 교차참조: %d개 실시간 자막을 VOD 전사 힌트로 사용", len(live_subs))

        # 2-패스 화자구분 준비 — 등록 의원 목소리(있으면 실명 라벨)를 1회 로드.
        do_diarize = settings.vod_diarize_enable_second_pass
        known_speakers: list[tuple[str, str]] = []
        if do_diarize:
            try:
                from app.services.voiceprint_service import voiceprint_service

                known_speakers = await asyncio.to_thread(
                    voiceprint_service.get_known_speakers_for_meeting, meeting_id
                ) or []
            except Exception as e:
                logger.debug("voiceprint known-speakers 스킵: %s", e)
        diarize_segments: list[dict] = []
        diarize_lock = asyncio.Lock()

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        n = len(chunks)
        sem = asyncio.Semaphore(_CHUNK_CONCURRENCY)
        results: list[tuple[list[dict], float] | None] = [None] * n
        failed: list[int] = []
        done = 0

        async def run_one(i: int, chunk: tuple[Path, float, float]) -> None:
            nonlocal done
            chunk_path, offset, chunk_dur = chunk
            # 청크 시간창과 겹치는 라이브 자막을 prompt 힌트로 덧붙임(시간정렬 교차참조)
            chunk_prompt = glossary_prompt + self._chunk_live_context(
                live_subs, offset, offset + chunk_dur
            )
            async with sem:
                subs, duration, ok = await self._transcribe_chunk(
                    client, i, chunk_path, offset, chunk_dur, dictionary,
                    meeting_id, chunk_prompt, delete_chunk=not do_diarize,
                )
            results[i] = (subs, duration)
            if not ok:
                failed.append(i)
            # 2-패스: 같은 청크 파일로 화자 라벨만 추출 (본문 텍스트는 위 transcribe 유지)
            if do_diarize and chunk_path.exists():
                try:
                    async with sem:
                        segs = await self._diarize_one_chunk(
                            client, chunk_path, offset, known_speakers
                        )
                    if segs:
                        async with diarize_lock:
                            diarize_segments.extend(segs)
                finally:
                    chunk_path.unlink(missing_ok=True)
            done += 1
            self._update_task(
                task, 0.25 + 0.65 * (done / max(1, n)),
                f"OpenAI 전사 {done}/{n} 청크" + (f" (실패 {len(failed)})" if failed else ""),
            )

        await asyncio.gather(*(run_one(i, c) for i, c in enumerate(chunks)))

        all_subs: list[dict] = []
        total_duration = 0.0
        for r in results:
            if not r:
                continue
            subs, duration = r
            all_subs.extend(subs)
            total_duration = max(total_duration, duration)
        all_subs.sort(key=lambda s: s["start_time"])  # 청크 순서 무관하게 시간순 보장

        # 커버리지 점검 — 자막 0개인 청크(무음 또는 전사 누락) 경고. 균일 청크라
        # 빈 청크가 많으면 분할/전사 문제 신호(과거 무음경계 청킹 누락 사고 회귀가드).
        empty_chunks = sum(1 for r in results if r and not r[0])
        if empty_chunks:
            logger.warning(
                "VOD 커버리지: %d/%d 청크가 자막 0개 (무음 또는 전사 누락 가능)",
                empty_chunks, n,
            )

        # 2-패스 화자 라벨 부여 (병합 전 — 같은 화자 자막 병합이 화자 경계를 존중하게)
        if do_diarize and diarize_segments:
            self._assign_speakers(all_subs, diarize_segments)
            labeled = sum(1 for s in all_subs if s.get("speaker"))
            logger.info(
                "VOD 화자구분: %d개 세그먼트 → 자막 %d/%d개에 화자 라벨 부여",
                len(diarize_segments), labeled, len(all_subs),
            )

        if failed and len(failed) == n:
            raise Exception(f"모든 청크({n}개) 전사 실패 — 자막 미생성")
        if failed:
            task.message = (
                f"부분 완료 — {n - len(failed)}/{n} 청크 성공 (실패 청크: {sorted(failed)})"
            )
            logger.warning("VOD 일부 청크 전사 실패: %d/%d (실패 %s)", len(failed), n, sorted(failed))

        # 병합 후 환각 재검사 — diarize가 영어 환각을 짧은 조각들로 반환하면
        # 각 조각이 필터를 통과한 뒤 같은 화자로 병합되며 영어 덩어리가 된다.
        # 병합 결과에 한 번 더 적용해 그런 케이스를 제거한다.
        merged = self._merge_short_utterances(all_subs)
        clean = [s for s in merged if not _is_hallucination(s["text"])]
        return clean, total_duration

    async def _transcribe_chunk(
        self,
        client: AsyncOpenAI,
        i: int,
        chunk_path: Path,
        offset: float,
        chunk_dur: float,
        dictionary,
        meeting_id: str,
        glossary_prompt: str = "",
        delete_chunk: bool = True,
    ) -> tuple[list[dict], float, bool]:
        """단일 mp3 청크 전사(재시도 포함). 반환: (자막목록, 청크끝시각, 성공여부).

        chunk_path는 처리 후 항상 삭제한다. glossary_prompt가 있으면 전사 모델에
        한국어 용어 바이어스로 주입한다 (diarize 모델 미지원 시 자동 폴백).
        """
        use_diarize = settings.vod_use_diarization
        use_whisper = settings.vod_use_whisper and not use_diarize
        resp = None
        use_prompt = bool(glossary_prompt)
        try:
            for attempt in range(_CHUNK_RETRIES + 1):
                try:
                    with open(chunk_path, "rb") as f:
                        if use_diarize:
                            kwargs = dict(
                                model=settings.diarize_model,
                                file=(chunk_path.name, f, "audio/mpeg"),
                                response_format="diarized_json",
                                chunking_strategy="auto",
                                language="ko",
                            )
                        elif use_whisper:
                            # whisper-1: 세그먼트별 '실제 타임스탬프' → 영상 동기화 정확
                            kwargs = dict(
                                model="whisper-1",
                                file=(chunk_path.name, f, "audio/mpeg"),
                                response_format="verbose_json",
                                timestamp_granularities=["segment"],
                                language="ko",
                            )
                        else:
                            # gpt-4o-transcribe (타임스탬프 없음 — 글자수비례 폴백)
                            kwargs = dict(
                                model=settings.live_batch_model,
                                file=(chunk_path.name, f, "audio/mpeg"),
                                language="ko",
                            )
                        if use_prompt:
                            kwargs["prompt"] = glossary_prompt
                        resp = await asyncio.wait_for(
                            client.audio.transcriptions.create(**kwargs),
                            timeout=_OPENAI_TIMEOUT,
                        )
                    break
                except Exception as e:
                    # prompt 미지원이면(400/타입오류) prompt 없이 재시도
                    if use_prompt and ("prompt" in str(e).lower() or "400" in str(e)):
                        logger.info("청크 %d: prompt 미지원 — prompt 없이 재시도", i)
                        use_prompt = False
                        continue
                    logger.warning(
                        "청크 %d 전사 실패(attempt %d/%d): %s",
                        i, attempt + 1, _CHUNK_RETRIES + 1, e,
                    )
                    if attempt < _CHUNK_RETRIES:
                        await asyncio.sleep(2 ** attempt)
        finally:
            if delete_chunk:
                chunk_path.unlink(missing_ok=True)

        if resp is None:
            return [], 0.0, False

        chunk_end = offset + float(chunk_dur)
        subs: list[dict] = []
        hallucinated = 0

        def _emit(text: str, seg_start: float, seg_end: float, speaker: str | None) -> None:
            nonlocal hallucinated
            text = (text or "").strip()
            if not text or _is_filler(text):
                return
            if _is_hallucination(text):
                hallucinated += 1
                return
            if dictionary:
                text = dictionary.correct(text)
            text = _strip_english_tail(text)  # 'yeah 그' / '네, yeah.' 영어 추임새 제거
            text = convert_korean_numerals(text)
            # 예산 금액 결정론 재표기 (보수적 — 원/예산 문맥이 확실한 숫자열만)
            text = normalize_amount_runs(text)
            # 긴 발언을 문장 단위로 분리 (1~2문장 자막)
            for stext, ss, se in split_sentences_with_timestamps(text, seg_start, seg_end):
                if _is_filler(stext) or _is_hallucination(stext):
                    continue
                subs.append({
                    "meeting_id": meeting_id,
                    "text": stext,
                    "start_time": round(ss, 2),
                    "end_time": round(se, 2),
                    "confidence": None,
                    "speaker": speaker,
                })

        if use_diarize:
            # 화자구분 모드: segments[].speaker, 길이는 응답 duration
            duration = offset + float(_attr(resp, "duration", 0) or chunk_dur)
            for seg in _attr(resp, "segments") or []:
                _emit(
                    str(_attr(seg, "text", "") or ""),
                    float(_attr(seg, "start", 0) or 0) + offset,
                    float(_attr(seg, "end", 0) or 0) + offset,
                    _speaker_label(_attr(seg, "speaker")),
                )
        elif use_whisper:
            # whisper 모드: 세그먼트별 '실제 시각'을 그대로 사용(글자수 비례 추정 X) →
            # 영상-자막 동기화가 정확. 짧은 세그먼트는 이후 _merge_short_utterances가 묶음.
            duration = offset + float(_attr(resp, "duration", 0) or chunk_dur)
            for seg in _attr(resp, "segments") or []:
                _emit(
                    str(_attr(seg, "text", "") or ""),
                    float(_attr(seg, "start", 0) or 0) + offset,
                    float(_attr(seg, "end", 0) or 0) + offset,
                    None,
                )
        else:
            # gpt-4o-transcribe 모드: 청크 전체 텍스트 → 글자수 비례 문장 타임스탬프
            duration = chunk_end
            _emit(_attr(resp, "text", "") or "", offset, chunk_end, None)

        if hallucinated:
            logger.info("청크 %d: 환각/반복 세그먼트 %d개 제거", i, hallucinated)
        return subs, duration, True

    # ─── 화자구분 2-패스 (본문 transcribe + diarize 화자라벨만) ───

    async def _diarize_one_chunk(
        self,
        client: AsyncOpenAI,
        chunk_path: Path,
        offset: float,
        known_speakers: list[tuple[str, str]],
    ) -> list[dict]:
        """단일 청크를 diarize 배치로 처리해 '절대시각 화자 세그먼트'만 반환(텍스트 미사용).

        본문 전사는 gpt-4o-transcribe가 담당하고 여기선 speaker 라벨만 얻는다 →
        diarize의 낮은 전사품질·영어환각을 회피. known_speakers(등록 의원 목소리)가
        있으면 'A/B' 대신 실제 의원명. 실패는 빈 리스트(화자구분 실패해도 본문 유지).
        """
        try:
            with open(chunk_path, "rb") as f:
                kwargs = dict(
                    model=settings.diarize_model,
                    file=(chunk_path.name, f, "audio/mpeg"),
                    response_format="diarized_json",
                    chunking_strategy="auto",
                    language="ko",
                )
                if known_speakers:
                    kwargs["extra_body"] = {
                        "known_speaker_names": [n for n, _ in known_speakers],
                        "known_speaker_references": [d for _, d in known_speakers],
                    }
                resp = await asyncio.wait_for(
                    client.audio.transcriptions.create(**kwargs),
                    timeout=_OPENAI_TIMEOUT,
                )
        except Exception as e:
            logger.warning("VOD diarize 청크 실패(offset=%.0fs): %s", offset, e)
            return []
        out: list[dict] = []
        for seg in _attr(resp, "segments") or []:
            label = _speaker_label(_attr(seg, "speaker"))
            s = float(_attr(seg, "start", 0) or 0) + offset
            e = float(_attr(seg, "end", 0) or 0) + offset
            if label and e > s:
                out.append({"start": s, "end": e, "speaker": label})
        return out

    @staticmethod
    def _assign_speakers(subtitles: list[dict], segments: list[dict]) -> None:
        """diarize 세그먼트를 자막에 시간겹침으로 매칭해 speaker를 부여(in-place).

        텍스트는 건드리지 않는다. 겹침이 가장 큰 세그먼트의 화자를 쓰고, 겹치는
        세그먼트가 없으면 화자 미부여(None 유지). 본문과 화자세그는 같은 청크 시계라
        직접 겹침으로 충분하다.
        """
        if not segments:
            return
        for sub in subtitles:
            s0 = float(sub.get("start_time", 0) or 0)
            s1 = float(sub.get("end_time", s0) or s0)
            if s1 < s0:
                s1 = s0
            best = None
            best_overlap = 0.0
            for seg in segments:
                overlap = min(s1, seg["end"]) - max(s0, seg["start"])
                if overlap > best_overlap:
                    best_overlap = overlap
                    best = seg
            if best is not None and best_overlap > 0.0:
                sub["speaker"] = best["speaker"]

    @staticmethod
    async def _extract_audio_chunks(mp4_path: Path) -> list[tuple[Path, float, float]]:
        """ffmpeg로 MP4 오디오를 mono 16kHz 64kbps mp3 '균일' 청크로 분할.

        ★균일 분할(누락 사고 후 원복): 모든 오디오 구간이 작은 청크 하나에 정확히
          들어가 누락 위험이 작다. 무음경계 가변 청킹은 과대 청크→전사 실패→대형
          공백(자막 40% 누락)을 냈다. 오프셋은 실제 길이(ffprobe) 누적 — 마지막
          짧은 청크까지 정확.

        반환: (청크경로, 시작오프셋초, 길이초) 목록. 호출자가 사용 후 삭제.
        """
        out_dir = Path(tempfile.mkdtemp(prefix="vodchunk_"))
        pattern = str(out_dir / "chunk_%03d.mp3")
        try:
            # VOD 등록 직후 낮에도 자동으로 돈다(2026-09-10) — 생중계 STT 가 먼저이게 우선순위를 낮춘다.
            proc = await asyncio.create_subprocess_exec(
                *LOW_PRIORITY,
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", str(mp4_path),
                "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "libmp3lame", "-b:a", "64k",
                "-f", "segment", "-segment_time", str(_TARGET_CHUNK_SECONDS),
                "-reset_timestamps", "1",
                pattern,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise Exception("ffmpeg가 설치되어 있지 않습니다 (VOD 전사 불가).")
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise Exception(f"ffmpeg 분할 실패: {stderr[:300].decode('utf-8', 'ignore')}")

        chunks = sorted(out_dir.glob("chunk_*.mp3"))
        # 실제 길이를 ffprobe로 재서 오프셋을 누적 (마지막 짧은 청크까지 정확)
        out: list[tuple[Path, float, float]] = []
        acc = 0.0
        for c in chunks:
            dur = await VodSttService._probe_duration(c)
            out.append((c, round(acc, 3), round(dur, 3)))
            acc += dur
        return out

    @staticmethod
    async def _probe_duration(path: Path) -> float:
        """mp3 청크의 실제 재생 길이(초)를 ffprobe로 잰다. 실패 시 목표 길이로 폴백."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await proc.communicate()
            return float(out.decode("utf-8", "ignore").strip() or _TARGET_CHUNK_SECONDS)
        except Exception:
            return float(_TARGET_CHUNK_SECONDS)

    @staticmethod
    def _merge_short_utterances(
        subtitles: list[dict],
        gap_threshold: float = 1.0,
        min_length: int = 15,
        max_merge_chars: int = 120,
    ) -> list[dict]:
        """같은 화자의 짧은/근접 자막을 병합하되, ~1-2문장(max_merge_chars)까지만.

        ★기존엔 같은 화자의 1초 미만 간격 세그먼트를 무한 병합해 한 화자의 긴
        발언이 수십 문장 한 덩어리가 됐다(사용자 지적). prev가 이미 충분히
        길면(max_merge_chars) 병합을 멈추고 새 자막을 시작한다.
        """
        if not subtitles:
            return subtitles

        merged: list[dict] = []
        for sub in subtitles:
            if merged:
                prev = merged[-1]
                same_speaker = prev.get("speaker") == sub.get("speaker")
                time_gap = sub.get("start_time", 0) - prev.get("end_time", 0)
                # ★짧은 단편(min_length 미만)만 인접 자막에 붙인다. 정상 길이의
                #   완결 문장끼리는 합치지 않아 1~2문장 단위를 유지한다.
                #   (둘 다 정상 길이면 병합 X → 한 화자 발언이 긴 덩어리로 안 뭉침)
                cur_short = len(sub.get("text", "")) < min_length
                prev_short = len(prev["text"]) < min_length
                if (
                    same_speaker
                    and len(prev["text"]) < max_merge_chars
                    and time_gap < gap_threshold
                    and (cur_short or prev_short)
                ):
                    prev["text"] = prev["text"] + " " + sub["text"]
                    prev["end_time"] = sub.get("end_time", prev["end_time"])
                    # confidence는 None일 수 있으므로 None-safe 처리
                    pc, sc = prev.get("confidence"), sub.get("confidence")
                    if pc is not None and sc is not None:
                        prev["confidence"] = (pc + sc) / 2
                    elif sc is not None:
                        prev["confidence"] = sc
                    continue
            merged.append(dict(sub))
        return merged

    # ─── 다운로드 ───

    @staticmethod
    async def _download_to_file(
        vod_url: str,
        task: SttTaskStatus,
        timeout_seconds: float = 3600.0,
        max_retries: int = 12,
    ) -> Path:
        """VOD를 임시 파일에 스트리밍 다운로드.

        대용량(1GB+) 파일은 서버가 전송 도중 연결을 끊는 일이 잦다(ClientPayloadError).
        받은 지점부터 HTTP Range로 이어받고, 폭넓은 전송오류(ClientError/Timeout)에 재시도해
        끝까지 받는다. (과거: ClientPayloadError가 재시도 대상이 아니라 즉시 실패했음.)

        ★병렬 다운로드 우선(2026-06-16): KMS는 '연결당' 스로틀(단일 ~0.3MB/s)이라
          16개 병렬 Range 연결이면 집계 ~3MB/s(~9배). 1.6GB VOD가 2.5시간→~8분.
          실측 확인. 병렬 실패(Range 미지원 등) 시 기존 단일연결 aiohttp로 폴백.
        """
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()

        # 1) 병렬 Range 다운로드 (KMS 연결당 스로틀 우회 — 압도적으로 빠름)
        try:
            from app.services.parallel_download import download_parallel

            task.message = "VOD 다운로드 중 (병렬 16연결)"
            size = await asyncio.to_thread(
                download_parallel, vod_url, str(tmp_path), 16
            )
            if size > 1_000_000:
                logger.info("병렬 다운로드 완료: %.0f MB", size / (1024 * 1024))
                return tmp_path
        except Exception as e:
            logger.warning("병렬 다운로드 실패 → 단일연결 폴백: %s", e)

        # 2) 폴백: 단일연결 스트리밍(이어받기) — Range 미지원/병렬 실패 시
        downloaded = 0
        total_size = 0
        last_exc: Exception | None = None

        for attempt in range(max_retries):
            try:
                downloaded, total_size = await VodSttService._download_attempt(
                    vod_url, tmp_path, downloaded, task, timeout_seconds
                )
                if total_size and downloaded < total_size:
                    raise aiohttp.ClientPayloadError(
                        f"불완전 다운로드 {downloaded}/{total_size}"
                    )
                if downloaded < 1_000_000:
                    tmp_path.unlink(missing_ok=True)
                    raise VodDownloadError(
                        f"다운로드된 파일이 비정상적으로 작습니다 ({downloaded} bytes)."
                    )
                return tmp_path
            except VodDownloadError:
                tmp_path.unlink(missing_ok=True)
                raise
            except (aiohttp.ClientError, ConnectionError, asyncio.TimeoutError, OSError) as e:
                last_exc = e
                wait = min(2 ** attempt, 30)
                logger.warning(
                    "VOD 다운로드 중단 (attempt %d/%d, %d MB 수신, %ds 후 이어받기): %s",
                    attempt + 1, max_retries, downloaded // (1024 * 1024), wait, e,
                )
                task.message = (
                    f"다운로드 이어받기 ({attempt + 1}/{max_retries}, "
                    f"{downloaded // (1024 * 1024)}MB)"
                )
                await asyncio.sleep(wait)

        tmp_path.unlink(missing_ok=True)
        raise VodDownloadError(
            f"VOD 다운로드 실패 (재시도 {max_retries}회 초과): {last_exc}"
        )

    @staticmethod
    async def _download_attempt(
        vod_url: str,
        tmp_path: Path,
        start_byte: int,
        task: SttTaskStatus,
        timeout_seconds: float,
    ) -> tuple[int, int]:
        """단일 다운로드 시도(이어받기 지원). 반환: (총 수신 바이트, 전체 크기).

        start_byte>0이면 Range로 이어받기를 시도. 서버가 206을 주면 append,
        200(Range 미지원)이면 처음부터 다시 받는다.
        """
        timeout = aiohttp.ClientTimeout(total=timeout_seconds, connect=30.0, sock_read=120.0)
        # KMS 보안정책(2026-07-21): 비브라우저 UA 차단 → 브라우저형 헤더 필수
        from app.services.kms_vod_resolver import KMS_BROWSER_HEADERS

        headers = dict(KMS_BROWSER_HEADERS)
        if start_byte > 0:
            headers["Range"] = f"bytes={start_byte}-"

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(vod_url, headers=headers) as response:
                if response.status not in (200, 206):
                    raise VodDownloadError(f"VOD 다운로드 실패: HTTP {response.status}")

                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" in content_type:
                    raise VodDownloadError(
                        "KMS 서버가 영상 대신 에러 페이지를 반환했습니다. "
                        "이 영상은 현재 제공되지 않을 수 있습니다."
                    )

                resuming = response.status == 206 and start_byte > 0
                if resuming:
                    total_size = 0
                    cr = response.headers.get("Content-Range", "")  # bytes s-e/total
                    if "/" in cr:
                        try:
                            total_size = int(cr.rsplit("/", 1)[1])
                        except ValueError:
                            total_size = 0
                    downloaded = start_byte
                    mode = "ab"
                else:
                    total_size = response.content_length or 0
                    if 0 < total_size < 1_000_000:
                        raise VodDownloadError(
                            f"VOD 파일 크기가 비정상적으로 작습니다 ({total_size} bytes). "
                            "KMS에서 이 영상이 제공되지 않을 수 있습니다."
                        )
                    downloaded = 0
                    mode = "wb"

                check_head = not resuming
                with open(tmp_path, mode) as f:
                    async for chunk in response.content.iter_chunked(512 * 1024):
                        if check_head:
                            check_head = False
                            head = chunk[:512].decode("utf-8", errors="ignore").lower()
                            if "<html" in head or "charset=euc-kr" in head:
                                raise VodDownloadError(
                                    "KMS 서버가 영상 대신 에러 페이지를 반환했습니다. "
                                    "이 영상은 현재 제공되지 않을 수 있습니다."
                                )
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            task.progress = 0.08 + 0.1 * (downloaded / total_size)
                            task.message = (
                                f"VOD 다운로드 중 ({downloaded // (1024*1024)}/"
                                f"{total_size // (1024*1024)} MB)"
                            )
                        else:
                            task.progress = 0.1
                            task.message = f"VOD 다운로드 중 ({downloaded // (1024*1024)} MB)"

                return downloaded, total_size

    # ─── 유틸 ───

    @staticmethod
    def _update_task(task: SttTaskStatus, progress: float, message: str) -> None:
        task.progress = progress
        task.message = message
        logger.info("[%s] %.0f%% - %s", task.meeting_id, progress * 100, message)

    @staticmethod
    async def _update_meeting_status(
        supabase: Client,
        meeting_id: str,
        status: str,
        *,
        duration_seconds: int | None = None,
        subtitle_stage: str | None = None,
    ) -> None:
        data: dict = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}
        if duration_seconds is not None:
            data["duration_seconds"] = duration_seconds
        if subtitle_stage is not None:
            data["subtitle_stage"] = subtitle_stage
        supabase.table("meetings").update(data).eq("id", meeting_id).execute()

    @staticmethod
    def _should_promote_to_ai(supabase: Client, meeting_id: str) -> bool:
        """현재 subtitle_stage가 none/draft일 때만 'ai' 승격(속기사 검토본 reviewing/final은 보존)."""
        try:
            r = (
                supabase.table("meetings").select("subtitle_stage")
                .eq("id", meeting_id).limit(1).execute()
            )
            cur = (r.data[0].get("subtitle_stage") if r.data else None) or "none"
            return cur in ("none", "draft")
        except Exception:
            return True

    @staticmethod
    async def _insert_subtitles(supabase: Client, subtitles: list[dict]) -> None:
        # AI 자막 — 실시간 자막(kind='live')과 구분해 비교 가능하게 저장
        for s in subtitles:
            s.setdefault("kind", "ai")
        supabase.table("subtitles").insert(subtitles).execute()
