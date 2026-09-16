"""화자 단서 추적기 — 상임위 회의 구조 기반 실시간 화자 추적.

상임위 회의는 위원장이 회의 내내 진행하며 다음 질의 위원을 호명하고, 위원은 순차적으로
≤2회 질의하며 집행부 실·국장과 대화한다(동시 발언 ≤2명). 이 구조를 이용해 실시간 확정
자막에서 단서를 감지하여 채널별 '현재 질의 위원'과 '현재 집행부 직책'을 추적한다.

diarize(경로 B)는 [위원장 + 현재 위원 + 직전 위원]의 voiceprint를 동적 known-speaker로
사용하고, 익명(A/B) 클러스터는 현재 집행부 라벨로 보정한다.

감지 단서:
  - 호명:     "다음은 OO 위원 질의", "OO 위원님 질의하시기 바랍니다"
  - 자기소개:  "OO 위원입니다"
  - 집행부:    "OO 국장/실장/과장 답변" → 직책 라벨

이름은 14~15명 위원회 명부와 difflib 퍼지 매칭으로 검증하므로 STT 오인식을 견딘다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

from app.core.channels import get_committee_for_channel
from app.core.config import settings
from app.core.database import get_supabase_client

logger = logging.getLogger(__name__)

# "OO 위원/의원"(위원장 제외) — 이름 후보 추출. 경기도의회=위원, 국회=의원 모두 지원.
# 위원장(위원+장)은 negative lookahead로 제외.
_MEMBER_RE = re.compile(r"([가-힣]{2,4})\s*(?:위원(?!장)|의원)")
# 발언 전환 맥락 (호명/자기소개 신호). STT가 "질의해"를 깨뜨려도 "주시기/바랍니다"로 포착.
_TURN_CONTEXT = ("질의", "발언", "말씀", "하시기", "주시기", "바랍니다", "하겠습니다", "수고", "답변", "차례")
_SELFINTRO_RE = re.compile(r"([가-힣]{2,4})\s*(?:위원|의원)\s*입니다")
# 집행부 직책 (의원 아님). 직책 목록을 명시(바 '관'은 과매칭이라 제외). 단독/접두 이름 모두.
_OFFICIAL_RE = re.compile(r"([가-힣]{0,8}?(?:장관|차관|차장|실장|국장|과장|부장|본부장|단장|청장|원장|팀장))")


def _norm(name: str) -> str:
    return re.sub(r"\s+", "", name or "").replace("의원", "").replace("위원", "").replace("님", "")


@dataclass
class _ChannelState:
    committee: Optional[str] = None
    chair_id: Optional[str] = None
    # (normalized_name, councilor_id, has_voiceprint)
    roster_index: list[tuple[str, str, bool]] = field(default_factory=list)
    # 명부 표시 이름(자막 본문 이름 교정용)
    roster_display: list[str] = field(default_factory=list)
    # 집행부 공무원 이름 명부 (staff_roster — 자막 본문 staff 이름 교정용)
    staff_names: list[str] = field(default_factory=list)
    current_member_id: Optional[str] = None
    prev_member_id: Optional[str] = None
    current_official_title: Optional[str] = None


class SpeakerCueTracker:
    """채널별 회의 구조 상태 머신."""

    def __init__(self) -> None:
        self._states: dict[str, _ChannelState] = {}

    # ─── lifecycle ───────────────────────────────────────────────────

    def start_channel(self, channel_id: str, meeting_id: str) -> None:
        """채널 STT 시작 시 위원회 명부·위원장을 로드한다.

        ★명부 로드는 cue_tracking_enabled와 무관하게 항상 수행한다(이름 사후교정의
        전제). cue 관찰(동적 화자추적)만 observe()에서 플래그로 가드한다 — 과거엔 여기서
        조기 반환해 플래그 OFF 시 라이브 이름교정까지 함께 죽어 VOD와 비대칭이었다.
        """
        state = _ChannelState()
        try:
            committee = self._resolve_committee(channel_id, meeting_id)
            state.committee = committee
            if committee:
                # 집행부 공무원 명부 — 위원회 해석 직후 로드 (자막 본문 staff 이름 교정용).
                # load_staff_roster 자체가 fail-soft(테이블 미존재 시 빈 리스트)이며,
                # voiceprint 명부 로드보다 먼저 두어 그쪽 실패에 연좌되지 않게 한다.
                from app.services.staff_roster_service import (
                    load_staff_roster,
                    staff_names as _staff_name_list,
                )
                state.staff_names = _staff_name_list(
                    load_staff_roster(get_supabase_client(), committee)
                )
                from app.services.voiceprint_service import voiceprint_service
                roster = voiceprint_service.get_committee_roster(committee)
                state.roster_index = [
                    (_norm(r["name"]), r["councilor_id"], bool(r.get("has_voiceprint")))
                    for r in roster if r.get("name") and r.get("councilor_id")
                ]
                state.roster_display = [r["name"] for r in roster if r.get("name")]
                for r in roster:
                    if r.get("is_chair"):
                        state.chair_id = r["councilor_id"]
                        break
                logger.info(
                    "CueTracker ch=%s committee=%s roster=%d chair=%s staff=%d",
                    channel_id, committee, len(state.roster_index), state.chair_id,
                    len(state.staff_names),
                )
        except Exception as e:
            logger.debug("CueTracker start failed ch=%s: %s", channel_id, e)
        self._states[channel_id] = state

    def drop_channel(self, channel_id: str) -> None:
        self._states.pop(channel_id, None)

    def _resolve_committee(self, channel_id: str, meeting_id: str) -> Optional[str]:
        committee = None
        try:
            if meeting_id and meeting_id != channel_id:
                m = (
                    get_supabase_client().table("meetings").select("committee, channel_id")
                    .eq("id", meeting_id).limit(1).execute()
                )
                if m.data:
                    committee = m.data[0].get("committee")
        except Exception:
            pass
        if not committee:
            committee = get_committee_for_channel(channel_id)
        return committee

    # ─── observation ─────────────────────────────────────────────────

    def observe(self, channel_id: str, text: str) -> bool:
        """확정 자막 텍스트에서 단서를 감지해 상태를 갱신. 변경되면 True.

        cue 관찰(동적 화자추적)은 플래그로 가드하지만, roster_names()(이름 사후교정용)는
        플래그와 무관하게 항상 동작한다.
        """
        if not settings.cue_tracking_enabled:
            return False
        state = self._states.get(channel_id)
        if state is None or not text:
            return False
        changed = False

        # 1) 집행부 직책 (의원 아님). "위원장"이 "원장"으로 오인식되지 않게 "위원" 포함은 제외.
        off = _OFFICIAL_RE.search(text)
        if off:
            title = off.group(1).strip()
            if title and "위원" not in title and title != state.current_official_title:
                state.current_official_title = title
                changed = True

        # 2) 위원 호명/자기소개 → 현재 질의 위원
        has_context = any(k in text for k in _TURN_CONTEXT) or bool(_SELFINTRO_RE.search(text))
        if state.roster_index and has_context:
            for m in _MEMBER_RE.finditer(text):
                matched = self._match_roster(state, m.group(1))
                if matched is None:
                    continue
                cid = matched
                if cid != state.current_member_id:
                    state.prev_member_id = state.current_member_id
                    state.current_member_id = cid
                    changed = True
                break  # 한 자막에서 첫 매칭 위원만
        return changed

    def _match_roster(self, state: _ChannelState, candidate: str) -> Optional[str]:
        """후보 이름을 명부와 퍼지 매칭해 councilor_id 반환 (임계값 미달이면 None)."""
        cand = _norm(candidate)
        if len(cand) < 2:
            return None
        best_id = None
        best_ratio = settings.cue_match_threshold
        for name_n, cid, _has_vp in state.roster_index:
            r = SequenceMatcher(None, cand, name_n).ratio()
            if r > best_ratio:
                best_ratio = r
                best_id = cid
        return best_id

    # ─── queries (diarize가 사용) ─────────────────────────────────────

    def current_known_councilor_ids(self, channel_id: str) -> list[str]:
        """[위원장, 현재 위원, 직전 위원] 중 voiceprint 보유자 ≤max, 중복 제거."""
        state = self._states.get(channel_id)
        if state is None:
            return []
        vp_ids = {cid for (_n, cid, has_vp) in state.roster_index if has_vp}
        ordered: list[str] = []
        for cid in (state.chair_id, state.current_member_id, state.prev_member_id):
            if cid and cid not in ordered and (cid in vp_ids or cid == state.chair_id):
                ordered.append(cid)
        return ordered[: settings.diarize_max_known_speakers]

    def current_member_name(self, channel_id: str) -> Optional[str]:
        """현재 질의 위원의 명부 표시 이름 (미상이면 None) — live_corrector 화자 힌트용."""
        state = self._states.get(channel_id)
        if state is None or not state.current_member_id:
            return None
        for name_n, cid, _has_vp in state.roster_index:
            if cid == state.current_member_id:
                for disp in state.roster_display:
                    if _norm(disp) == name_n:
                        return disp
                return name_n
        return None

    def current_official_label(self, channel_id: str) -> str:
        """집행부 라벨. 직책을 알면 '집행부 OO국장', 아니면 '집행부'."""
        state = self._states.get(channel_id)
        if state and state.current_official_title:
            return f"집행부 {state.current_official_title}"
        return "집행부"

    def in_questioning_turn(self, channel_id: str) -> bool:
        """현재 위원 질의 턴인지(집행부 relabel 적용 맥락)."""
        state = self._states.get(channel_id)
        return bool(state and state.current_member_id)

    def roster_names(self, channel_id: str) -> list[str]:
        """채널 위원회 명부의 표시 이름 목록 (자막 본문 이름 교정용)."""
        state = self._states.get(channel_id)
        return list(state.roster_display) if state else []

    def staff_names(self, channel_id: str) -> list[str]:
        """채널 위원회의 집행부 공무원 이름 목록 (자막 본문 staff 이름 교정용)."""
        state = self._states.get(channel_id)
        return list(state.staff_names) if state else []


# 싱글톤 (경로 A·B 공유)
speaker_cue_tracker = SpeakerCueTracker()
