#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""얼굴 인식 정확도 실측 — 임계값(`face_cos_*`)을 정하는 근거를 만든다.

무엇을 재는가
-------------
회의 VOD 에서 **한 의원이 이어서 발언하는 구간**의 한가운데 프레임을 뽑는다. 그 순간 카메라는
그 의원을 잡고 있으므로, 자막의 발언자 이름이 곧 화면 속 인물의 **독립적인 정답 후보**가 된다
(자막 발언자는 음성으로 정해진 값이라 얼굴 인식과 증거가 겹치지 않는다).

세 가지를 낸다:
  * **정밀도** — 이름을 붙인 얼굴 중 발언자와 일치한 비율. 담당자가 화면에서 실제로 보는 값이다.
  * **재현율** — 발언자가 화면에 잡힌 프레임 중 이름을 붙인 비율.
  * **점수 분포** — 맞은 것과 틀린 것의 코사인 점수. 임계값은 이 둘이 갈리는 자리에 둔다.

쓰는 법 (오르카서버):
    python3 backend/scripts/eval_face_matching.py --api https://<poc-app 공인 IP>/transcribe \\
        --models <모델 폴더> --out eval_out --meetings 5 --per-meeting 12

⚠ 이 스크립트는 **읽기만** 한다 — DB 에 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from collections import Counter, defaultdict

import cv2
import numpy as np
import httpx

# face_engine 만 파일 경로로 직접 읽는다 — `app.services` 패키지를 통하면 supabase 등
# 서비스 전체 의존성이 끌려 들어와, 모델만 있으면 되는 이 스크립트가 못 돈다.
import importlib.util  # noqa: E402

_FE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "services", "face_engine.py"
)
_spec = importlib.util.spec_from_file_location("face_engine", _FE_PATH)
_fe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fe)
ArcFaceEmbedder, ScrfdDetector = _fe.ArcFaceEmbedder, _fe.ScrfdDetector

warnings.filterwarnings("ignore")  # 검증환경은 자체서명 인증서라 verify=False 로 부른다

PHOTO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://www.ggc.go.kr/",
}


def api_get(base: str, path: str, **params):
    r = httpx.get(f"{base}{path}", params=params, timeout=60, verify=False)
    r.raise_for_status()
    return r.json()


def build_gallery(base: str, det, emb, cache_dir: str) -> tuple[np.ndarray, list[str], dict]:
    """공식 사진으로 명부 임베딩을 만든다(로컬 캐시)."""
    os.makedirs(cache_dir, exist_ok=True)
    rows = api_get(base, "/api/councilors")
    mat, owner, meta = [], [], {}
    for r in rows:
        meta[r["id"]] = r
        url = r.get("profile_image_url")
        if not url:
            continue
        p = os.path.join(cache_dir, f"{r['id']}.jpg")
        if not os.path.exists(p):
            try:
                resp = httpx.get(url, headers=PHOTO_HEADERS, timeout=30, follow_redirects=True)
                if resp.status_code != 200 or len(resp.content) < 2000:
                    continue
                open(p, "wb").write(resp.content)
            except Exception:
                continue
        img = cv2.imread(p)
        if img is None:
            continue
        b, k = det.detect(img, score_thresh=0.35)
        if len(b) == 0:
            continue
        i = int(np.argmax((b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])))
        mat.append(emb.embed(img, k[i:i + 1])[0])
        owner.append(r["id"])
    return np.asarray(mat, dtype=np.float32), owner, meta


def fetch_subtitles(base: str, meeting_id: str, page: int = 1000, cap: int = 20000) -> list[dict]:
    """회의 자막 전체 — API 한 번에 1000건까지라 offset 으로 넘긴다."""
    out: list[dict] = []
    while len(out) < cap:
        got = api_get(base, f"/api/meetings/{meeting_id}/subtitles", limit=page, offset=len(out))
        rows = got if isinstance(got, list) else (got.get("items") or got.get("subtitles") or [])
        if not rows:
            break
        out.extend(rows)
        if len(rows) < page:
            break
    out.sort(key=lambda r: float(r.get("start_time") or 0))
    return out


def speech_turns(subs: list[dict], min_seconds: float, max_turns: int) -> list[tuple[str, float]]:
    """같은 발언자가 이어지는 구간 → (이름, 한가운데 초)."""
    turns, cur, start, end = [], None, 0.0, 0.0
    for s in subs:
        spk = (s.get("speaker") or "").strip()
        name = spk.split()[0] if spk else ""
        if name != cur:
            if cur and (end - start) >= min_seconds:
                turns.append((cur, (start + end) / 2))
            cur, start = name, float(s.get("start_time") or 0)
        end = float(s.get("end_time") or s.get("start_time") or 0)
    if cur and (end - start) >= min_seconds:
        turns.append((cur, (start + end) / 2))
    # 사람을 고루 담는다 — 한 명이 표본을 독차지하면 정확도가 그 사람 얼굴 난이도로 수렴한다
    by_name: dict[str, list] = defaultdict(list)
    for n, t in turns:
        by_name[n].append(t)
    out = []
    while len(out) < max_turns and any(by_name.values()):
        for n in list(by_name):
            if by_name[n]:
                out.append((n, by_name[n].pop(len(by_name[n]) // 2)))
            if len(out) >= max_turns:
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True, help="서비스 API 주소 (예: https://IP/transcribe)")
    ap.add_argument("--models", required=True, help="det_10g.onnx · w600k_r50.onnx 가 있는 폴더")
    ap.add_argument("--out", default="eval_face_out")
    ap.add_argument("--meetings", type=int, default=5)
    ap.add_argument("--per-meeting", type=int, default=12)
    ap.add_argument("--min-turn-seconds", type=float, default=25.0)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--accept", type=float, default=0.42)
    ap.add_argument("--margin", type=float, default=0.06)
    ap.add_argument("--min-px", type=int, default=48)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    det = ScrfdDetector(os.path.join(args.models, "det_10g.onnx"), num_threads=args.threads)
    emb = ArcFaceEmbedder(os.path.join(args.models, "w600k_r50.onnx"), num_threads=args.threads)

    print("명부 적재 중…", flush=True)
    mat, owner, meta = build_gallery(args.api, det, emb, os.path.join(args.out, "portraits"))
    name_of = {cid: meta[cid]["name"] for cid in owner}
    print(f"  템플릿 {len(owner)}개")

    meetings = [m for m in api_get(args.api, "/api/meetings", limit=40) if m.get("vod_url")]
    meetings = meetings[: args.meetings]

    records = []
    for m in meetings:
        committee = m.get("committee") or ""
        subs = fetch_subtitles(args.api, m["id"])
        turns = speech_turns(subs, args.min_turn_seconds, args.per_meeting * 3)
        # 위원회 후보 제한
        allow = {cid for cid in owner
                 if any((c.get("name") or "").replace(" ", "") == committee.replace(" ", "")
                        for c in (meta[cid].get("committees") or []))}
        idx = [i for i, o in enumerate(owner) if o in allow] if len(allow) >= 5 else list(range(len(owner)))
        sub_mat = mat[idx]
        sub_owner = [owner[i] for i in idx]
        uniq = list(dict.fromkeys(sub_owner))
        rows_of = {cid: np.where(np.asarray(sub_owner) == cid)[0] for cid in uniq}

        cap = cv2.VideoCapture(m["vod_url"])
        if not cap.isOpened():
            print(f"  [건너뜀] VOD 를 열지 못함 — {m['title']}")
            continue
        taken = 0
        for name, t in turns:
            if taken >= args.per_meeting:
                break
            if not name or len(name) < 2 or name in ("위원장", "집행부", "(미지정)"):
                continue
            if not any(meta[cid]["name"] == name for cid in uniq):
                continue  # 이 위원회 명부에 없는 발언자(집행부 등)
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            taken += 1
            h, w = frame.shape[:2]
            b, k = det.detect(frame, score_thresh=0.5)
            if len(b) == 0:
                records.append({"meeting": m["title"], "committee": committee, "t": t,
                                "truth": name, "faces": 0, "hit": False, "named": None, "score": 0.0})
                continue
            V = emb.embed(frame, k)
            S = V @ sub_mat.T
            best_named, best_score, correct = None, 0.0, False
            for i in range(len(b)):
                if (b[i][2] - b[i][0]) < args.min_px:
                    continue
                per = np.asarray([S[i][rows_of[cid]].max() for cid in uniq], dtype=np.float32)
                order = np.argsort(-per)
                sc = float(per[order[0]])
                mg = sc - float(per[order[1]]) if len(order) > 1 else sc
                if sc >= args.accept and mg >= args.margin:
                    nm = meta[uniq[order[0]]]["name"]
                    if sc > best_score:
                        best_named, best_score = nm, sc
                    if nm == name:
                        correct = True
                        best_named, best_score = nm, sc
                        break
            records.append({"meeting": m["title"], "committee": committee, "t": round(t, 1),
                            "truth": name, "faces": int(len(b)), "hit": correct,
                            "named": best_named, "score": round(best_score, 3)})
            cv2.imwrite(os.path.join(args.out, f"{m['id'][:8]}_{int(t)}_{name}.jpg"), frame)
        cap.release()
        print(f"  {m['meeting_date']} {committee}: 표본 {taken}", flush=True)

    json.dump(records, open(os.path.join(args.out, "records.json"), "w"), ensure_ascii=False, indent=1)

    named = [r for r in records if r["named"]]
    right = [r for r in named if r["hit"]]
    with_face = [r for r in records if r["faces"] > 0]
    print("\n=== 결과 ===")
    print(f"표본 {len(records)} · 얼굴 잡힘 {len(with_face)} · 이름 붙임 {len(named)} · 발언자와 일치 {len(right)}")
    if named:
        print(f"정밀도(이름 붙인 것 중 발언자와 일치) {len(right)/len(named)*100:.1f}%")
    if with_face:
        print(f"재현율(얼굴 잡힌 것 중 발언자 이름 붙임) {len(right)/len(with_face)*100:.1f}%")
    wrong = [r for r in named if not r["hit"]]
    if wrong:
        print("\n일치하지 않은 것 (화면에 다른 의원이 함께 잡혔을 수 있다 — 눈으로 확인할 것):")
        for r in wrong[:15]:
            print(f"  {r['committee']} {r['t']}s 발언자={r['truth']} → {r['named']} ({r['score']})")
    print("\n점수 분포:", Counter([round(r["score"], 1) for r in named]).most_common())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
