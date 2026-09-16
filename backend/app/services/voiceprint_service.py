"""의원 목소리 샘플(voiceprint) 서비스 — 실명 화자 식별.

gpt-4o-transcribe-diarize의 known_speaker_references에 넘길 2~10초 음성 샘플을
등록/조회/선택한다. 등록 시 ffmpeg로 16kHz mono wav로 정규화하고 ≤10초로 트림한 뒤
base64로 Supabase에 저장한다(Railway 파일시스템 휘발성 회피).

회의 단위로는 해당 위원회에 등록된 ≤4명(API 한도)을 골라 (이름, data URL) 쌍으로 반환한다.
역할(위원장) 정보가 동기화 데이터에 없으므로, 관리자가 등록한 순서(created_at)로 상한을 적용한다.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import wave
from datetime import datetime, timezone
from typing import Optional

from app.core.channels import get_committee_for_channel
from app.core.config import settings
from app.core.database import get_supabase_client
from app.services.councilor_sync import CouncilorSyncService

logger = logging.getLogger(__name__)

_FFMPEG_TIMEOUT = 30.0


class VoiceprintError(Exception):
    """등록 실패(샘플 너무 짧음/디코딩 실패 등)."""


async def _to_wav_16k_mono(audio_bytes: bytes, max_seconds: float) -> Optional[bytes]:
    """임의 오디오 → 16kHz mono wav(≤max_seconds)로 정규화. 실패 시 None."""
    rate = settings.voiceprint_sample_rate
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", "pipe:0",
            "-t", str(max_seconds),
            "-vn", "-ac", "1", "-ar", str(rate),
            "-f", "wav", "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.error("ffmpeg not installed — voiceprint enrollment unavailable")
        return None
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=audio_bytes), timeout=_FFMPEG_TIMEOUT
        )
    except asyncio.TimeoutError:
        proc.kill()
        logger.warning("ffmpeg timeout converting voiceprint sample")
        return None
    if proc.returncode != 0 or len(stdout) < 100:
        logger.warning("ffmpeg voiceprint convert failed (rc=%s): %s",
                       proc.returncode, stderr[:200].decode("utf-8", "ignore"))
        return None
    return stdout


def _wav_duration_ms(wav_bytes: bytes) -> int:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate() or settings.voiceprint_sample_rate
            return int(frames / rate * 1000)
    except Exception:
        return 0


class VoiceprintService:
    """의원 목소리 샘플 CRUD + 회의별 known-speaker 선택."""

    # ─── 등록 ────────────────────────────────────────────────────────

    async def enroll_from_bytes(
        self, councilor_id: str, audio_bytes: bytes, *, source: str = "upload"
    ) -> dict:
        """오디오 바이트를 16kHz wav로 정규화·검증 후 의원 목소리로 등록(upsert)."""
        if not audio_bytes:
            raise VoiceprintError("빈 오디오입니다.")

        supabase = get_supabase_client()
        councilor = (
            supabase.table("councilors").select("id, name, committees")
            .eq("id", councilor_id).limit(1).execute()
        )
        if not councilor.data:
            raise VoiceprintError(f"의원을 찾을 수 없습니다: {councilor_id}")
        c = councilor.data[0]
        name = c.get("name") or ""
        committee = _first_committee(c.get("committees"))

        wav = await _to_wav_16k_mono(audio_bytes, settings.voiceprint_max_seconds)
        if not wav:
            raise VoiceprintError("오디오 디코딩 실패(ffmpeg). 지원 형식의 음성 파일인지 확인하세요.")

        duration_ms = _wav_duration_ms(wav)
        if duration_ms < settings.voiceprint_min_seconds * 1000:
            raise VoiceprintError(
                f"샘플이 너무 짧습니다({duration_ms}ms). 최소 {settings.voiceprint_min_seconds:.0f}초 이상 필요."
            )

        b64 = base64.b64encode(wav).decode("ascii")
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "councilor_id": councilor_id,
            "councilor_name": name,
            "committee": committee,
            "sample_format": "audio/wav",
            "sample_b64": b64,
            "duration_ms": duration_ms,
            "source": source,
            "updated_at": now,
        }

        # upsert: 의원당 1개 (UNIQUE councilor_id)
        existing = (
            supabase.table("councilor_voiceprints").select("id")
            .eq("councilor_id", councilor_id).limit(1).execute()
        )
        if existing.data:
            supabase.table("councilor_voiceprints").update(row).eq(
                "councilor_id", councilor_id
            ).execute()
        else:
            row["created_at"] = now
            supabase.table("councilor_voiceprints").insert(row).execute()

        logger.info("Voiceprint enrolled: %s (%s, %dms, %s)", name, committee, duration_ms, source)
        return {
            "councilor_id": councilor_id,
            "councilor_name": name,
            "committee": committee,
            "duration_ms": duration_ms,
            "source": source,
        }

    # ─── 조회/삭제 ────────────────────────────────────────────────────

    def list_enrolled(self) -> list[dict]:
        """등록된 목소리 메타데이터 목록(샘플 base64 제외)."""
        res = (
            get_supabase_client().table("councilor_voiceprints")
            .select("councilor_id, councilor_name, committee, duration_ms, source, is_chair, created_at, updated_at")
            .order("committee")
            .execute()
        )
        return res.data or []

    # ─── 위원장 지정 / 명부 / 개별 조회 (구조 인지형 식별용) ─────────────

    def set_chair(self, councilor_id: str, is_chair: bool) -> bool:
        """의원을 소속 위원회의 위원장으로 지정/해제. 위원회당 위원장 1명을 보장."""
        supabase = get_supabase_client()
        res = (
            supabase.table("councilor_voiceprints").select("committee")
            .eq("councilor_id", councilor_id).limit(1).execute()
        )
        if not res.data:
            return False  # voiceprint가 있어야 위원장 지정 가능
        committee = res.data[0].get("committee")
        if is_chair and committee:
            # 같은 위원회 기존 위원장 해제 (1명 보장)
            supabase.table("councilor_voiceprints").update({"is_chair": False}).eq(
                "committee", committee
            ).eq("is_chair", True).execute()
        supabase.table("councilor_voiceprints").update({"is_chair": is_chair}).eq(
            "councilor_id", councilor_id
        ).execute()
        return True

    def get_chair_for_committee(self, committee: str) -> Optional[tuple[str, str]]:
        """위원회 위원장의 (이름, data URL). 미지정이면 None."""
        if not committee:
            return None
        res = (
            get_supabase_client().table("councilor_voiceprints")
            .select("councilor_name, sample_format, sample_b64")
            .eq("committee", committee).eq("is_chair", True).limit(1).execute()
        )
        return _to_known_speaker(res.data[0]) if res.data else None

    def get_voiceprint_for_councilor(self, councilor_id: str) -> Optional[tuple[str, str]]:
        """의원 개인의 (이름, data URL). 미등록이면 None."""
        res = (
            get_supabase_client().table("councilor_voiceprints")
            .select("councilor_name, sample_format, sample_b64")
            .eq("councilor_id", councilor_id).limit(1).execute()
        )
        return _to_known_speaker(res.data[0]) if res.data else None

    def get_committee_roster(self, committee: str) -> list[dict]:
        """위원회 명부 + voiceprint/위원장 상태. cue tracker의 이름 퍼지매칭에 사용.

        반환: [{councilor_id, name, has_voiceprint, is_chair}]
        """
        if not committee:
            return []
        supabase = get_supabase_client()
        try:
            councilors = CouncilorSyncService(supabase).get_by_committee(committee)
        except Exception as e:
            logger.debug("roster councilors query failed: %s", e)
            councilors = []
        ids = [c["id"] for c in councilors if c.get("id")]
        vp_map: dict[str, bool] = {}
        if ids:
            try:
                vp = (
                    supabase.table("councilor_voiceprints").select("councilor_id, is_chair")
                    .in_("councilor_id", ids).execute()
                )
                vp_map = {r["councilor_id"]: bool(r.get("is_chair")) for r in (vp.data or [])}
            except Exception as e:
                logger.debug("roster voiceprint query failed: %s", e)
        roster = []
        for c in councilors:
            cid = c.get("id")
            roster.append({
                "councilor_id": cid,
                "name": c.get("name"),
                "has_voiceprint": cid in vp_map,
                "is_chair": vp_map.get(cid, False),
            })
        return roster

    def get_status(self, councilor_id: str) -> dict:
        res = (
            get_supabase_client().table("councilor_voiceprints")
            .select("councilor_id, councilor_name, committee, duration_ms, source, updated_at")
            .eq("councilor_id", councilor_id).limit(1).execute()
        )
        if res.data:
            return {"enrolled": True, **res.data[0]}
        return {"enrolled": False, "councilor_id": councilor_id}

    def delete(self, councilor_id: str) -> bool:
        res = (
            get_supabase_client().table("councilor_voiceprints")
            .delete().eq("councilor_id", councilor_id).execute()
        )
        return bool(res.data)

    # ─── 회의별 known-speaker 선택 (diarize용) ─────────────────────────

    def get_known_speakers_for_meeting(self, meeting_id: str) -> list[tuple[str, str]]:
        """회의 위원회에 등록된 ≤max 명을 (이름, data URL)로 반환.

        diarize의 known_speaker_names/known_speaker_references로 전달된다.
        위원회를 알 수 없으면 빈 리스트(추측하지 않음 → 순번 라벨 폴백).
        """
        if not settings.diarize_known_speakers_enabled:
            return []
        supabase = get_supabase_client()

        committee: Optional[str] = None
        try:
            m = (
                supabase.table("meetings").select("committee, channel_id")
                .eq("id", meeting_id).limit(1).execute()
            )
            if m.data:
                committee = m.data[0].get("committee")
                if not committee and m.data[0].get("channel_id"):
                    committee = get_committee_for_channel(m.data[0]["channel_id"])
        except Exception as e:
            logger.debug("known-speaker committee resolve failed: %s", e)

        if not committee:
            return []

        try:
            res = (
                supabase.table("councilor_voiceprints")
                .select("councilor_name, sample_format, sample_b64")
                .eq("committee", committee)
                .order("created_at")  # 관리자 등록 순서 = 우선순위
                .limit(settings.diarize_max_known_speakers)
                .execute()
            )
            rows = res.data or []
        except Exception as e:
            logger.warning("known-speaker query failed (meeting=%s): %s", meeting_id, e)
            return []

        out: list[tuple[str, str]] = []
        for r in rows:
            name = r.get("councilor_name")
            b64 = r.get("sample_b64")
            fmt = r.get("sample_format") or "audio/wav"
            if name and b64:
                out.append((name, f"data:{fmt};base64,{b64}"))
        return out


def _to_known_speaker(row: dict) -> tuple[str, str]:
    """voiceprint 행 → (이름, data URL)."""
    fmt = row.get("sample_format") or "audio/wav"
    return (row.get("councilor_name") or "", f"data:{fmt};base64,{row.get('sample_b64')}")


def _first_committee(committees) -> Optional[str]:
    """councilors.committees(JSONB [{name,role}])에서 첫 위원회명."""
    if isinstance(committees, list):
        for item in committees:
            if isinstance(item, dict) and item.get("name"):
                return item["name"]
    return None


# 싱글톤
voiceprint_service = VoiceprintService()
