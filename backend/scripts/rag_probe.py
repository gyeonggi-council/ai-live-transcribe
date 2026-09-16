"""AI 대화 검색 확인 도구(2026-09-15) — 질문마다 어떤 자막이 AI 에 넘어가는지 표로 본다. OpenAI 호출·DB 쓰기 없음.

  dump  : 운영 api 파드 안에서 SELECT 만 해 회의 JSON 을 stdout 으로
          kubectl -n ggc-poc exec -i deploy/ggc-live-transcribe-api -c api -- python - dump <meeting_id> < scripts/rag_probe.py > m.json
  local : 저장한 JSON 으로 지금 코드의 build_meeting_context 를 돌린다(배포 전 확인)
          PYTHONPATH=. python scripts/rag_probe.py local m.json
  live  : 운영 파드 안에서 ai_rag_service._meeting_context 를 그대로 부른다(배포 후 확인)
          kubectl -n ggc-poc exec -i deploy/ggc-live-transcribe-api -c api -- python - live <meeting_id> < scripts/rag_probe.py
"""
import asyncio
import json
import re
import sys

# (질문, 이전 사용자 질문들, 발췌에 들어가야 할 시각 접두어, 들어가면 안 되는 문자열)
CASES = [
    ("이자형의원이 발언한 것중에 모바일 공무원증은 없어?", [], ["04:28", "04:29", "04:30"], []),
    ("모바일 공무원증", [], ["04:28"], []),
    ("이자영 의원이 모바일 공무원증 얘기했어?", [], ["04:28"], []),
    ("모바일 공무원증 얘기 나왔어?", [], ["04:28"], []),
    ("그거 누가 말했어?", ["모바일 공무원증 얘기 나왔어?"], ["04:28"], []),
    ("그 사람은 뭐라고 했어?", ["모바일 공무원증 얘기 나왔어?", "그거 누가 말했어?"], ["04:28"], []),
    ("5번 안건 결과는?", [], [], []),
    ("공무국외출장규칙 결과는?", [], [], []),
    ("진용국 사무처장 답변 요약", [], [], []),
    ("이 회의를 요약해 줘", [], [], []),
]


def _history(prev):
    out = []
    for q in prev:
        out += [{"role": "user", "content": q}, {"role": "assistant", "content": "(이전 답변)"}]
    return out


def _row(q, prev, want, bad, bundle):
    t = bundle.text
    ex = t.split("=== 자막 발췌 ===\n", 1)[-1]
    st = bundle.stats
    ok_want = all(any(line.startswith(f"[{w}") for line in ex.splitlines()) for w in want)
    ok_bad = not any(b in ex for b in bad)
    guide = next((line for line in ex.splitlines() if line.startswith("[검색 안내]")), "")
    return {"q": q, "level": st.get("level"), "mode": st.get("mode"), "hits": st.get("hits"), "chars": st.get("chars"),
            "names": st.get("names"), "terms": st.get("terms"), "want_ok": ok_want, "bad_ok": ok_bad,
            "모바일": ex.count("모바일"), "sources": [s["start_time"] for s in bundle.sources], "guide": guide[:160]}


def dump(mid):
    from app.core.database import get_supabase
    from app.services.roster_loader import load_committee_with_roles
    from app.services.subtitle_fetch import fetch_all_subtitles
    from app.services.subtitle_select import prefer_ai_subtitles
    sb = get_supabase()
    meeting = sb.table("meetings").select("id, title, meeting_date, committee, duration_seconds, status").eq("id", mid).limit(1).execute().data[0]
    subs = prefer_ai_subtitles(fetch_all_subtitles(sb, mid))
    subs = [{k: s.get(k) for k in ("id", "start_time", "end_time", "text", "speaker", "kind")} for s in subs]
    summ = (sb.table("meeting_summaries").select("*").eq("meeting_id", mid).limit(1).execute().data or [None])[0]
    agendas = sb.table("meeting_agendas").select("order_num, title").eq("meeting_id", mid).order("order_num").execute().data or []
    roster = [m["name"] for m in load_committee_with_roles(sb, meeting.get("committee"))]
    json.dump({"meeting": meeting, "subtitles": subs, "summary": summ, "agendas": [a for a in agendas if a.get("title")],
               "roster": roster}, sys.stdout, ensure_ascii=False, default=str)


def local(path):
    from app.services import rag_context
    d = json.load(open(path, encoding="utf-8"))
    for q, prev, want, bad in CASES:
        b = rag_context.build_meeting_context(subtitles=d["subtitles"], meeting=d["meeting"], summary_row=d["summary"],
                                              agendas=d["agendas"], question=q, history=_history(prev), roster=d["roster"])
        print(json.dumps(_row(q, prev, want, bad, b), ensure_ascii=False))


def live(mid):
    from app.core.database import get_supabase
    from app.services import ai_rag_service as rag
    sb = get_supabase()

    async def go():
        for q, prev, want, bad in CASES:
            ctx = await rag._meeting_context(sb, q, mid, _history(prev))
            blk = ctx[0]

            class B:
                text, stats, sources = blk["text"], blk["stats"], blk["sources"]
            print(json.dumps(_row(q, prev, want, bad, B), ensure_ascii=False))
    asyncio.run(go())


if __name__ == "__main__":
    mode, arg = sys.argv[1], sys.argv[2]
    {"dump": dump, "local": local, "live": live}[mode](arg)
