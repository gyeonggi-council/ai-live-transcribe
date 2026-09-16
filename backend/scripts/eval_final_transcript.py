"""AI 최종본 A/B 평가 하네스.

사용법:
  python scripts/eval_final_transcript.py --meeting <id> --reference ref.txt

reference.txt(사람이 교정한 정답)가 있으면 CER을 계산한다.
없으면 처리시간 + 변경률만 출력한다.
"""

import argparse
import asyncio
import time


def cer(ref: str, hyp: str) -> float:
    """문자 오류율 근사(1 - 매칭문자 / len(ref))."""
    import difflib

    sm = difflib.SequenceMatcher(None, ref, hyp)
    matches = sum(b.size for b in sm.get_matching_blocks())
    if not ref:
        return 0.0
    return 1.0 - matches / len(ref)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--meeting", required=True)
    parser.add_argument("--reference", default=None)
    args = parser.parse_args()

    from app.core.database import get_supabase_client
    from app.services.final_transcript_service import (
        FinalTaskStatus,
        _make_openai_client,
        _retranscribe_vod,
        correct_segments_with_llm,
    )
    from app.services.glossary_service import format_glossary_prompt, load_meeting_glossary

    sb = get_supabase_client()
    m = sb.table("meetings").select("vod_url").eq("id", args.meeting).limit(1).execute().data
    if not m or not m[0].get("vod_url"):
        print("VOD URL이 없는 회의입니다.")
        return
    vod_url = m[0]["vod_url"]

    t0 = time.time()
    task = FinalTaskStatus(meeting_id=args.meeting)
    segments = await _retranscribe_vod(args.meeting, vod_url, task)
    t_retx = time.time() - t0
    raw_text = " ".join(s.get("text", "") for s in segments)

    glossary = format_glossary_prompt(load_meeting_glossary(sb, args.meeting))
    client = _make_openai_client()
    t1 = time.time()
    corrected = await correct_segments_with_llm(
        client=client,
        segments=segments,
        glossary_prompt=glossary,
        hint_texts=[],
        model="gpt-5-mini",
    )
    t_corr = time.time() - t1
    corr_text = " ".join(s.get("text", "") for s in corrected)

    print(f"재전사 시간: {t_retx:.1f}s, 교정 시간: {t_corr:.1f}s")
    print(f"세그먼트 수: {len(segments)}")
    if args.reference:
        with open(args.reference, encoding="utf-8") as f:
            ref = f.read()
        print(f"CER(재전사):      {cer(ref, raw_text):.3f}")
        print(f"CER(재전사+교정): {cer(ref, corr_text):.3f}")


if __name__ == "__main__":
    asyncio.run(main())
