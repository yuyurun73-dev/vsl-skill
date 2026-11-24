#!/usr/bin/env python3
"""ショットリスト → 制作計画一式を吐く。

shotlist.json（人間＆Claudeが読む唯一の正本）から
  telopspec.json  … テロップPNG用（render_telop.py に渡す）
  manifest.json   … 組み立て用（assemble.py に渡す）
  todo.json       … まだ無い素材の一覧（TTS・動画生成・在庫欠番）
を生成する。素材が揃ったら同じコマンドを再実行すればtodoが減る＝再開可能。

使い方:
  python3 build_plan.py <project_dir>/shotlist.json

shotlist.json:
{
  "name": "silen-oxygen-v4",
  "brand": "silen",
  "size": [1080, 1920],
  "fps": 30,
  "scenes": [
    {"id": "S01",
     "source": {"type": "stock", "path": "/abs/Broll01_....mp4", "start": 0},
     "lines": [{"id": "S01-1", "vo": "読ませる原文", "telop": "帯に出す文<r>赤</r>"}]},

    {"id": "S02",
     "source": {"type": "avatar"},                 # VO長に合わせてリップシンク生成
     "lines": [...]},

    {"id": "S03",
     "source": {"type": "generate", "prompt": "…", "ref": "/abs/persona.png"},
     "lines": [...]},

    {"id": "S04", "source": {"type": "stock", "path": "..."}, "dur": 2.5, "lines": []}
  ],
  "endcard": {"image": "/abs/cta.png", "dur": 3.0},
  "bgm": {"path": "/abs/bgm.mp3", "db": -26}
}

- telop 省略時は vo をそのまま帯に出す（読点は帯側で削る）
- source.path が実在しなければ todo.clips に載る（＝生成が要る）
- vo/<id>.mp3 が無ければ todo.vo に載る
"""
import json, os, sys

CACHE = os.path.expanduser("~/.claude/skills/vsl/cache")
_CAUTION = {}


def caution_fix(video, brand):
    """カタログの caution を読み、焼き込み字幕やワイプを画面外に出すzoom/anchorを返す。

    素材に他人のテロップが乗ったまま出るのを機械的に防ぐ。
    どうしても消せない素材（画面中央に大きく焼かれている等）は差し替えるしかない。
    """
    if not brand:
        return None, None
    if brand not in _CAUTION:
        p = os.path.join(CACHE, brand, "catalog.json")
        _CAUTION[brand] = ({c["path"]: c.get("caution", "")
                            for c in json.load(open(p))["clips"]} if os.path.exists(p) else {})
    c = _CAUTION[brand].get(video, "")
    # 判定順に注意。「下を切るかテロップ帯で隠す」にも"テロップ"が含まれるので
    # 「大きく焼き込み」を先に見る。
    if "テロップが大きく" in c:  # 画面7割あたりに大きく焼かれている → 下3割を捨てる
        return 1.5, "top"
    if "字幕" in c:            # 下部の字幕 → 下3割を捨てる（1.3では消えない素材がある）
        return 1.5, "top"
    if "ワイプ" in c:          # 右上のワイプ → 拡大して左寄せ＝右上を切る
        return 1.3, "left"
    return None, None


def cutaway_plan(sl, base, size):
    """HeyGenベースがある時の計画。timeline.json（align.pyの出力）が要る。

    各行の秒はtimelineから来る。シーンの source が stock/generate なら
    そのシーンの行が喋られている区間に映像を被せる（＝カットアウェイ）。
    source.type が "base" または省略のシーンは、アバターを映したままにする。
    """
    tl_path = os.path.join(base, "timeline.json")
    if not os.path.exists(tl_path):
        return None, {"align": [{"need": "timeline.json",
                                 "how": "python3 align.py <base動画> shotlist.json"}]}
    tl = {l["id"]: l for l in json.load(open(tl_path))["lines"]}

    telop_items, telop_cues, cutaways, todo = [], [], [], {"clips": [], "missing_stock": []}
    for sc in sl["scenes"]:
        sid = sc["id"]
        ids = []
        for i, ln in enumerate(sc.get("lines", []), 1):
            lid = ln.get("id") or f"{sid}-{i}"
            ids.append(lid)
            t = tl.get(lid)
            if not t:
                continue
            text = ln.get("telop", ln["vo"])
            if text:
                telop_items.append({"id": lid, "text": text})
                telop_cues.append({"start": t["start"], "end": t["end"],
                                   "png": os.path.join("telop", f"{lid}.png")})

        src = sc.get("source", {})
        stype = src.get("type", "base")
        if stype == "base" or not ids:
            continue
        spans = [tl[i] for i in ids if i in tl]
        if not spans:
            continue
        start = min(s["start"] for s in spans) + sc.get("lead", 0.0)
        end = max(s["end"] for s in spans) + sc.get("tail", 0.25)

        if stype == "stock":
            path = src.get("path", "")
            if not (path and os.path.exists(path)):
                todo["missing_stock"].append({"scene": sid, "wanted": path})
                continue
        else:
            path = os.path.join(base, "clips", f"{sid}.mp4")
            if not os.path.exists(path):
                todo["clips"].append({"scene": sid, "type": stype, "out": path,
                                      "prompt": src.get("prompt"), "ref": src.get("ref"),
                                      "need_sec": round(end - start, 2)})
                continue
        cutaways.append({"start": round(start, 3), "end": round(end, 3),
                         "video": path, "in": src.get("start", 0.0)})

    mf = {"name": sl.get("name", "vsl"), "size": size, "fps": sl.get("fps", 30),
          "base": sl["base"], "cutaways": cutaways, "telop": telop_cues,
          "loudnorm": sl.get("loudnorm", True)}
    if sl.get("endcard"):
        mf["endcard"] = sl["endcard"]
    return (mf, telop_items), todo


def main():
    sl_path = os.path.abspath(sys.argv[1])
    sl = json.load(open(sl_path))
    base = os.path.dirname(sl_path)
    for d in ("vo", "telop", "clips", "scenes"):
        os.makedirs(os.path.join(base, d), exist_ok=True)

    size = sl.get("size", [1080, 1920])

    if sl.get("base"):                       # HeyGenアバター版
        got, todo = cutaway_plan(sl, base, size)
        if got is None:
            with open(os.path.join(base, "todo.json"), "w") as f:
                json.dump(todo, f, ensure_ascii=False, indent=1)
            print(json.dumps({"mode": "cutaway", "blocked": "timeline.json が無い",
                              "next": "align.py を先に回す"}, ensure_ascii=False))
            return
        mf, telop_items = got
        with open(os.path.join(base, "telopspec.json"), "w") as f:
            json.dump({"size": size, "y": sl.get("telop_y", int(size[1] * 0.52)),
                       "outdir": os.path.join(base, "telop"), "items": telop_items},
                      f, ensure_ascii=False, indent=1)
        with open(os.path.join(base, "manifest_cutaway.json"), "w") as f:
            json.dump(mf, f, ensure_ascii=False, indent=1)
        with open(os.path.join(base, "todo.json"), "w") as f:
            json.dump(todo, f, ensure_ascii=False, indent=1)
        print(json.dumps({"mode": "cutaway", "telop": len(telop_items),
                          "cutaways": len(mf["cutaways"]),
                          "todo_clips": len(todo["clips"]),
                          "missing_stock": len(todo["missing_stock"]),
                          "ready": not (todo["clips"] or todo["missing_stock"])},
                         ensure_ascii=False))
        return

    todo = {"vo": [], "clips": [], "missing_stock": []}
    telop_items, scenes = [], []

    for sc in sl["scenes"]:
        sid = sc["id"]
        src = sc.get("source", {})
        stype = src.get("type", "stock")

        # --- 映像 ---
        if stype == "stock":
            path = src.get("path", "")
            if path and os.path.exists(path):
                video = path
            else:
                video = os.path.join(base, "clips", f"{sid}.mp4")
                todo["missing_stock"].append({"scene": sid, "wanted": path})
        else:
            video = os.path.join(base, "clips", f"{sid}.mp4")
            if not os.path.exists(video):
                todo["clips"].append({
                    "scene": sid, "type": stype, "out": video,
                    "prompt": src.get("prompt"), "ref": src.get("ref"),
                    "note": "avatarはVO長に合わせてリップシンク生成する" if stype == "avatar" else None,
                })

        # --- 行（VO＋テロップ） ---
        lines = []
        for i, ln in enumerate(sc.get("lines", []), 1):
            lid = ln.get("id") or f"{sid}-{i}"
            vo_path = os.path.join(base, "vo", f"{lid}.mp3")
            if not os.path.exists(vo_path):
                todo["vo"].append({"id": lid, "text": ln["vo"], "out": vo_path})
            telop_text = ln.get("telop", ln["vo"])
            if telop_text:
                telop_items.append({"id": lid, "text": telop_text})
            lines.append({
                "id": lid,
                "audio": os.path.relpath(vo_path, base),
                "telop": os.path.join("telop", f"{lid}.png") if telop_text else None,
                **({"gap": ln["gap"]} if "gap" in ln else {}),
            })

        scene = {"id": sid, "video": video, "lines": lines}
        z, anchor = caution_fix(video, sl.get("brand"))
        if z:
            scene["zoom"], scene["anchor"] = z, anchor
        if src.get("start"):
            scene["video_start"] = src["start"]
        if sc.get("dur"):
            scene["dur"] = sc["dur"]
        if sc.get("keep_source_audio"):
            scene["keep_source_audio"] = True
            scene["source_audio_db"] = sc.get("source_audio_db", -18)
        scenes.append(scene)

    tp = {"size": size, "y": sl.get("telop_y", int(size[1] * 0.52)),
          "outdir": os.path.join(base, "telop"), "items": telop_items}
    with open(os.path.join(base, "telopspec.json"), "w") as f:
        json.dump(tp, f, ensure_ascii=False, indent=1)

    mf = {"name": sl.get("name", "vsl"), "size": size, "fps": sl.get("fps", 30),
          "loudnorm": sl.get("loudnorm", True), "scenes": scenes}
    if sl.get("endcard"):
        mf["endcard"] = sl["endcard"]
    if sl.get("bgm"):
        mf["bgm"] = sl["bgm"]
    with open(os.path.join(base, "manifest.json"), "w") as f:
        json.dump(mf, f, ensure_ascii=False, indent=1)

    with open(os.path.join(base, "todo.json"), "w") as f:
        json.dump(todo, f, ensure_ascii=False, indent=1)

    print(json.dumps({
        "scenes": len(scenes), "telop": len(telop_items),
        "todo_vo": len(todo["vo"]), "todo_clips": len(todo["clips"]),
        "missing_stock": len(todo["missing_stock"]),
        "ready": not (todo["vo"] or todo["clips"] or todo["missing_stock"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
