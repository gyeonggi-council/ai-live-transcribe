"""라이브 자막 GPT 교정 서비스 — 글로서리 바이어스 사후 교정.

경로 A(openai_realtime_stt)가 확정한 자막을 채널별로 배치 수집한 뒤, 회의 글로서리
(용어사전+의원명+의안명)를 바이어스로 GPT 교정하여 정확도를 높이고, subtitle_corrected
이벤트로 프런트의 '교정 중'을 '교정됨'으로 전환한다.

설계 (사용자 요구: "10초 정도 딜레이돼도 좋으니 정확도를 높여줘"):
  - 자막은 즉시 표시('교정 중'), 배치(기본 4개) 또는 sweeper(기본 7초)마다 교정 → 화면 갱신.
  - GPT는 STT 오인식만 보정(숫자/의안번호/조례안명/직책/의원명). 의미 변경·내용 추가 금지,
    불확실하면 원문 유지 → 환각 방지.
  - 실패/무변경 시 broadcast_correction_failed로 pending 해제 → '교정 중'이 영원히 남지 않음.
  - 라이브 파이프라인과 독립(예외가 STT를 막지 않음). 채널별 동시 교정 1건.

화자 피기백 (A4 — 한계비용 ~0):
  - 같은 GPT 배치에 화자 추정을 얹는다(오디오 diarize는 계속 OFF). 응답 스키마 v2:
    {"0":{"t":"교정문","s":"화자"}} — 레거시 dict-of-strings도 방어적으로 수용.
  - 화자는 text_speaker_service._valid_speaker로 검증(명부 밖 'OO 위원' 거부 —
    없는 위원 생성 금지, staff 명부 실명은 staff_names로 인정). 유효하면 채널
    prev_speaker 갱신, 무효/단서 없음이면 직전 화자 유지(기본 "위원장").
  - ★diarize_enabled=True 구성이면 화자 피기백 전체 생략(diarize 라벨이 권위 —
    텍스트 추정 화자가 오디오 화자구분 결과를 덮어쓰는 경합 방지). 텍스트 교정만 수행.
  - 텍스트 무변경이라도 유효한 화자가 있으면 DB update + speaker 포함 브로드캐스트
    (websocket manager는 speaker-only 병합 지원). 텍스트도 화자도 없을 때만 실패 처리.
  - 명부/집행부 블록은 채널당 1회 lazy 로드, speaker_cue_tracker의 현재 단서
    (질의 위원명/집행부 직책)를 user 프롬프트 힌트로 주입.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from openai import AsyncOpenAI

from app.api.websocket import manager
from app.core.channels import get_committee_for_channel
from app.core.config import settings
from app.core.database import get_supabase_client
from app.services.glossary_service import format_glossary_prompt, load_meeting_glossary
from app.services.roster_loader import load_committee_with_roles
from app.services.speaker_cue_tracker import speaker_cue_tracker
from app.services.staff_roster_service import load_staff_roster, staff_glossary_terms
from app.services.text_speaker_service import _valid_speaker

logger = logging.getLogger(__name__)

_GPT_TIMEOUT = 30.0

_SYSTEM_PROMPT = (
    "당신은 경기도의회 회의 실시간 자막 교정기입니다. 음성 인식(STT) 결과의 오인식을 "
    "한국어 의회 회의 맥락에 맞게 교정하고, 각 줄의 화자를 추정합니다.\n"
    "교정 규칙:\n"
    "- 글로서리(고유명사·의안명·의원명·직책)가 주어지면 그 표기에 맞춰 교정한다.\n"
    "- 표결 인원수(재석/찬성/반대), 의안 번호('제N호'), 조례안·의안 명칭, 직책"
    "(위원장/국장/실장 등) 오인식을 우선 보정한다.\n"
    "- 의미를 바꾸지 말 것. 없는 내용을 추가하지 말 것. 확실하지 않으면 원문을 그대로 둔다.\n"
    "- 예산 금액: 긴 숫자 나열(예: 14100008000)은 오인식 — 문맥상 금액이면 "
    "14억8100만원처럼 억/만 단위 한국어 표기로 재구성. 확신 없으면 원문 유지.\n"
    "화자 규칙:\n"
    "- 화자(s)는 참석 위원 명부의 이름(예: 'OOO 위원', 'OOO 위원장') 또는 집행부 "
    "직책(예: 'OO국장', 'OO과장')으로만 표기한다.\n"
    "- 명부에 없는 이름에 '위원/위원장' 호칭을 절대 부여하지 않는다(없는 위원 생성 금지).\n"
    "- 위원의 질문 다음에 오는 답변(\"~입니다\", \"~하겠습니다\", \"~드리겠습니다\")은 "
    "집행부 직책으로 표기한다(자막에 등장한 직책, 못 찾으면 직전 화자 유지).\n"
    "- 진행 멘트(호명, '다음은', 상정, 의결, 선포, '이의 없으십니까')는 위원장.\n"
    "- 단서가 없으면 직전 화자를 그대로 쓴다.\n"
    "- 각 줄을 독립적으로 교정한다. 출력은 JSON 객체만: "
    "{\"0\":{\"t\":\"교정문\",\"s\":\"화자\"}, \"1\":{\"t\":\"교정문\",\"s\":\"화자\"}, ...}\n"
)


@dataclass
class _Pending:
    room_id: str
    meeting_id: str
    subtitle_id: str
    text: str


@dataclass
class _ChannelState:
    queue: list[_Pending] = field(default_factory=list)
    last_enqueue: float = field(default_factory=time.monotonic)
    glossary_prompt: Optional[str] = None  # None=미로드, ""=빈 글로서리(로드됨)
    roster_block: Optional[str] = None  # None=미로드 — 위원회 명부 프롬프트 블록
    staff_block: Optional[str] = None   # 집행부 공무원 명부 블록 (fail-soft)
    roster_names: set[str] = field(default_factory=set)  # 화자 검증용 위원 이름
    staff_names: frozenset[str] = frozenset()  # 화자 검증용 staff(출석 공무원) 이름
    prev_speaker: str = "위원장"  # 직전 화자 (단서 없으면 유지 — 회의는 위원장이 개의)


def _format_roster_block(roster: list[dict]) -> str:
    """[{name, role}] 명부를 역할별 프롬프트 블록으로 포맷. 비면 빈 문자열."""
    by_role: dict[str, list[str]] = {}
    for m in roster:
        by_role.setdefault(m.get("role") or "위원", []).append(m["name"])
    lines = []
    for role in ("위원장", "부위원장", "간사", "위원"):
        if by_role.get(role):
            lines.append(f"- {role}: {', '.join(by_role[role])}")
    if not lines:
        return ""
    return "참석 위원 명부(이 명단 외 이름에 위원 호칭 금지):\n" + "\n".join(lines)


class LiveCorrector:
    """채널별 자막 배치 → GPT 글로서리 교정 → subtitle_corrected 브로드캐스트."""

    def __init__(self) -> None:
        self._client: Optional[AsyncOpenAI] = None
        self._enabled = False
        self._states: dict[str, _ChannelState] = {}
        self._sweeper: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._inflight: set[str] = set()
        self._tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]

    # ─── lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        if not settings.live_correction_enabled:
            logger.info("LiveCorrector disabled via settings")
            return
        if not settings.openai_api_key:
            logger.warning("LiveCorrector: OPENAI_API_KEY 없음 — 비활성")
            return
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._enabled = True
        self._sweeper = asyncio.create_task(self._sweep_loop(), name="live-corrector-sweeper")
        logger.info(
            "LiveCorrector started (model=%s, batch=%d, flush=%.1fs)",
            settings.live_correction_model,
            settings.live_correction_batch_size,
            settings.live_correction_flush_seconds,
        )

    async def stop(self) -> None:
        if self._sweeper and not self._sweeper.done():
            self._sweeper.cancel()
            try:
                await self._sweeper
            except asyncio.CancelledError:
                pass
        self._sweeper = None
        live = [t for t in self._tasks if not t.done()]
        for t in live:
            t.cancel()
        if live:
            await asyncio.gather(*live, return_exceptions=True)
        self._tasks.clear()
        self._states.clear()
        self._inflight.clear()
        self._enabled = False
        logger.info("LiveCorrector stopped")

    def drop_channel(self, room_id: str) -> None:
        self._states.pop(room_id, None)
        self._inflight.discard(room_id)

    # ─── 입력 (경로 A의 _emit_subtitle에서 호출) ─────────────────────────

    def enqueue(self, room_id: str, meeting_id: str, subtitle_id: str, text: str) -> None:
        """확정 자막을 교정 큐에 넣는다. 배치가 차면 flush 트리거."""
        if not self._enabled or not text or not text.strip():
            return
        # meeting 미연결(채널-only 폴백) 세션은 DB 영속 자막이 없어 교정 가치가 낮고
        # GPT 비용만 발생 → 스킵. 프런트 pending은 안전 타임아웃이 해제한다.
        if not meeting_id or meeting_id == room_id:
            return
        st = self._states.setdefault(room_id, _ChannelState())
        st.queue.append(_Pending(room_id, meeting_id, subtitle_id, text))
        st.last_enqueue = time.monotonic()
        if len(st.queue) >= settings.live_correction_batch_size:
            self._flush(room_id)

    def _flush(self, room_id: str) -> None:
        st = self._states.get(room_id)
        if not st or not st.queue or room_id in self._inflight:
            return
        batch = st.queue
        st.queue = []
        self._inflight.add(room_id)
        t = asyncio.create_task(self._correct_and_apply(room_id, batch))
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _sweep_loop(self) -> None:
        """부분 배치가 오래 남으면 주기적으로 flush(단건도 일정 시간 내 교정)."""
        try:
            while True:
                await asyncio.sleep(settings.live_correction_flush_seconds)
                now = time.monotonic()
                stale = [
                    rid for rid, st in self._states.items()
                    if st.queue and now - st.last_enqueue >= settings.live_correction_flush_seconds
                ]
                for rid in stale:
                    self._flush(rid)
        except asyncio.CancelledError:
            return

    # ─── 교정 + 적용 ─────────────────────────────────────────────────

    async def _get_glossary(self, room_id: str, meeting_id: str) -> str:
        st = self._states.get(room_id)
        if st and st.glossary_prompt is not None:
            return st.glossary_prompt
        prompt = ""
        try:
            if meeting_id and meeting_id != room_id:
                terms = await asyncio.to_thread(
                    load_meeting_glossary, get_supabase_client(), meeting_id
                )
                # 호출마다 재전송되는 prompt → 글자수 캡으로 토큰 비용 상한
                prompt = format_glossary_prompt(terms, max_terms=120, max_chars=600)
        except Exception as e:
            logger.debug("LiveCorrector glossary load failed: %s", e)
        if st:
            st.glossary_prompt = prompt
        return prompt

    @staticmethod
    def _resolve_committee(room_id: str, meeting_id: str) -> Optional[str]:
        """채널의 위원회명 해석 — meeting.committee 우선, 채널 정적 매핑 폴백."""
        committee = None
        try:
            if meeting_id and meeting_id != room_id:
                m = (
                    get_supabase_client().table("meetings").select("committee")
                    .eq("id", meeting_id).limit(1).execute()
                )
                if m.data:
                    committee = m.data[0].get("committee")
        except Exception:
            committee = None
        if not committee:
            try:
                committee = get_committee_for_channel(room_id)
            except Exception:
                committee = None
        return committee

    async def _ensure_speaker_context(
        self, st: _ChannelState, room_id: str, meeting_id: str
    ) -> None:
        """위원회 명부/집행부 블록을 채널당 1회 lazy 로드 (fail-soft)."""
        if st.roster_block is not None:
            return
        roster_block = ""
        staff_block = ""
        names: set[str] = set()
        staff_name_set: frozenset[str] = frozenset()
        committee = await asyncio.to_thread(self._resolve_committee, room_id, meeting_id)
        if committee:
            try:
                roster = await asyncio.to_thread(
                    load_committee_with_roles, get_supabase_client(), committee
                )
                names = {m["name"] for m in roster if m.get("name")}
                roster_block = _format_roster_block(roster)
            except Exception as e:
                logger.debug("LiveCorrector roster load failed: %s", e)
            try:
                entries = await asyncio.to_thread(
                    load_staff_roster, get_supabase_client(), committee
                )
                terms = staff_glossary_terms(entries)
                if terms:
                    staff_block = "집행부 출석 공무원(답변 화자 후보): " + ", ".join(terms)
                # 화자 검증용 staff 실명 집합 — _valid_speaker(staff_names=)에 전달해
                # '배성호 건설국장' 같은 staff 실명 화자를 인정한다.
                staff_name_set = frozenset(
                    e["name"] for e in entries if e.get("name")
                )
            except Exception as e:
                logger.debug("LiveCorrector staff roster load failed: %s", e)
        st.roster_block = roster_block
        st.staff_block = staff_block
        st.roster_names = names
        st.staff_names = staff_name_set

    @staticmethod
    def _speaker_hints(room_id: str, st: _ChannelState) -> str:
        """직전 화자 + cue tracker 현재 단서(질의 위원/집행부 직책) 힌트."""
        hints = [f"직전 화자: {st.prev_speaker}"]
        try:
            member = speaker_cue_tracker.current_member_name(room_id)
            if member:
                hints.append(f"현재 질의 위원: {member}")
            label = speaker_cue_tracker.current_official_label(room_id)
            if label and label != "집행부":
                hints.append(f"현재 답변 집행부: {label}")
        except Exception as e:
            logger.debug("LiveCorrector cue hint skipped: %s", e)
        return " / ".join(hints)

    async def _correct_and_apply(self, room_id: str, batch: list[_Pending]) -> None:
        try:
            st = self._states.setdefault(room_id, _ChannelState())
            glossary = await self._get_glossary(room_id, batch[0].meeting_id)
            await self._ensure_speaker_context(st, room_id, batch[0].meeting_id)
            corrections = await self._call_gpt(room_id, batch, glossary, st)
            if corrections is None:
                # 교정 불가 → pending 해제(자막은 원문 유지)
                for p in batch:
                    await _safe_fail(room_id, p.subtitle_id, "correction unavailable")
                return
            # diarize(오디오 화자구분)가 켜져 있으면 diarize 라벨이 권위 —
            # 텍스트 추정 화자 피기백(DB update+브로드캐스트의 speaker)을 전체
            # 생략해 두 경로가 speaker를 서로 덮어쓰는 경합을 차단한다.
            speaker_piggyback = not settings.diarize_enabled
            for idx, p in enumerate(batch):
                raw = corrections.get(str(idx))
                speaker: Optional[str] = None
                if isinstance(raw, dict):
                    # v2 객체 스키마 {t, s} — 화자 검증(명부 밖 'OO 위원' 거부,
                    # staff 명부 실명은 staff_names로 인정)
                    new_text = (raw.get("t") or "").strip()
                    if speaker_piggyback:
                        cand = _valid_speaker(
                            raw.get("s") or "", st.roster_names, st.staff_names
                        )
                        if cand:
                            st.prev_speaker = cand
                            speaker = cand
                        else:
                            # 무효/단서 없음 → 직전 화자 유지 (없는 위원 생성 금지)
                            speaker = st.prev_speaker
                else:
                    # 레거시 dict-of-strings — 텍스트만 (화자 없음)
                    new_text = (raw or "").strip()
                text_changed = bool(new_text) and new_text != p.text.strip()
                if not text_changed and not speaker:
                    await _safe_fail(room_id, p.subtitle_id, "no change")
                    continue
                update_fields: dict[str, str] = {}
                if text_changed:
                    update_fields["text"] = new_text
                if speaker:
                    update_fields["speaker"] = speaker
                if p.meeting_id and p.meeting_id != room_id:
                    try:
                        await asyncio.to_thread(
                            lambda sid=p.subtitle_id, fields=dict(update_fields):
                            get_supabase_client()
                            .table("subtitles").update(fields).eq("id", sid).execute()
                        )
                    except Exception as e:
                        logger.debug("LiveCorrector db update failed: %s", e)
                payload: dict[str, str] = {
                    "id": p.subtitle_id,
                    "meeting_id": p.meeting_id,
                    "source": "gpt",
                }
                if text_changed:
                    payload["corrected_text"] = new_text
                if speaker:
                    payload["speaker"] = speaker
                try:
                    await manager.broadcast_corrected_subtitle(room_id, payload)
                except Exception as e:
                    logger.debug("LiveCorrector broadcast failed: %s", e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("LiveCorrector batch failed room=%s: %s", room_id, e)
        finally:
            self._inflight.discard(room_id)
            st = self._states.get(room_id)
            if st and st.queue:
                self._flush(room_id)

    async def _call_gpt(
        self, room_id: str, batch: list[_Pending], glossary: str, st: _ChannelState
    ) -> Optional[dict[str, object]]:
        if not self._client:
            return None
        numbered = "\n".join(f"{i}: {p.text}" for i, p in enumerate(batch))
        parts = [
            glossary,
            st.roster_block or "",
            st.staff_block or "",
            self._speaker_hints(room_id, st),
            numbered,
        ]
        user_content = "\n\n".join(p for p in parts if p)
        try:
            resp = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=settings.live_correction_model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    response_format={"type": "json_object"},
                    max_completion_tokens=settings.live_correction_max_tokens,
                ),
                timeout=_GPT_TIMEOUT,
            )
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            logger.warning("LiveCorrector GPT timeout")
            return None
        except Exception as e:
            logger.warning("LiveCorrector GPT call failed: %s", e)
            return None

        content = (resp.choices[0].message.content or "").strip()
        return _parse_corrections(content, len(batch))


def _parse_corrections(content: str, n: int) -> Optional[dict[str, object]]:
    """GPT JSON 응답 파싱(방어적).

    v2 객체 스키마({"0":{"t":"교정문","s":"화자"}})와 레거시 문자열 스키마
    ({"0":"교정문"}) 둘 다 수용한다 — 값은 dict{t,s} 또는 str.
    """
    if not content:
        return None
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    out: dict[str, object] = {}
    for i in range(n):
        v = data.get(str(i))
        if isinstance(v, str):
            out[str(i)] = v
        elif isinstance(v, dict):
            t = v.get("t")
            s = v.get("s")
            out[str(i)] = {
                "t": t if isinstance(t, str) else "",
                "s": s if isinstance(s, str) else "",
            }
    return out or None


async def _safe_fail(room_id: str, subtitle_id: str, reason: str) -> None:
    try:
        await manager.broadcast_correction_failed(room_id, subtitle_id, reason)
    except Exception as e:
        logger.debug("LiveCorrector fail-broadcast skipped: %s", e)


# 싱글톤 (경로 A·main lifespan에서 공유)
live_corrector = LiveCorrector()
