#!/usr/bin/env python3
"""長尺動画をショット単位に切り分けて素材化する。

他社VSLのような「1本に全シチュエーションが詰まった」動画から、
カットごとの短尺クリップを取り出して在庫に足すための道具。

使い方:
  # 1) 検出だけ（何カット取れるか見る）
  python3 extract_shots.py --brand silen --category swipe_competitor --detect-only

  # 2) 切り出し＋インデックス付きコンタクトシート
  python3 extract_shots.py --brand silen --category swipe_competitor

  # 3) 個別指定
  python3 extract_shots.py --files a.mp4 --out ~/.../shots

出力: <out>/<source>/NN.mp4 と shots.json、sheets/sheet-NN.png（通し番号つき）
番号は shots.json の "idx" と一致する。仕分けはその番号で指す。
"""
import argparse, html, json, math, os, re, subprocess, sys, tempfile

BROWSERS = ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")


def browser():
    for b in BROWSERS:
        if os.path.exists(b):
            return b
    sys.exit("Brave も Chrome も見つからない")


def dur_of(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", p], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def cut_points(path, thresh):
    """シーン変化の秒を返す。

    lavfi の movie= はパスにスペースや括弧が入ると壊れるので、
    ffmpeg に普通の引数としてファイルを渡し showinfo の pts_time を拾う。
    """
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", path,
         "-vf", f"select='gt(scene,{thresh})',showinfo",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True, timeout=3600)
    return sorted(float(m) for m in re.findall(r"pts_time:([\d.]+)", r.stderr))


def segments(path, thresh, min_d, max_d, cap):
    total = dur_of(path)
    pts = [0.0] + cut_points(path, thresh) + [total]
    segs = []
    for a, b in zip(pts, pts[1:]):
        d = b - a
        if d < min_d:
            continue
        segs.append({"start": round(a, 2), "dur": round(min(d, max_d), 2)})
    segs.sort(key=lambda s: -s["dur"])
    segs = segs[:cap]
    segs.sort(key=lambda s: s["start"])
    return segs, total


def slug(name):
    return re.sub(r"[^\w.-]", "_", os.path.splitext(name)[0])[:44]


def sheet_html(cells, cols, tw):
    body = []
    for c in cells:
        body.append(f'<figure><img src="file://{html.escape(c["thumb"])}">'
                    f'<figcaption><b>#{c["idx"]}</b> {c["dur"]}s<br>'
                    f'<span>{html.escape(c["src"])}</span></figcaption></figure>')
    return f"""<!doctype html><meta charset=utf-8>
<style>
 html,body{{margin:0;background:#0d0d0d;color:#fff;
   font-family:-apple-system,"Hiragino Sans",sans-serif}}
 .g{{display:grid;grid-template-columns:repeat({cols},{tw}px);gap:6px;padding:6px}}
 figure{{margin:0;background:#191919;border-radius:4px;overflow:hidden}}
 img{{width:{tw}px;display:block;background:#000}}
 figcaption{{padding:3px 5px;font-size:11px;line-height:1.35}}
 figcaption b{{color:#6cf}} figcaption span{{color:#777;font-size:9px;word-break:break-all}}
</style><div class=g>{''.join(body)}</div>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand")
    ap.add_argument("--category")
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("--thresh", type=float, default=0.35)
    ap.add_argument("--min-dur", type=float, default=1.5)
    ap.add_argument("--max-dur", type=float, default=6.0)
    ap.add_argument("--cap", type=int, default=40, help="1本あたりの最大カット数（長い順）")
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--rows", type=int, default=6)
    ap.add_argument("--detect-only", action="store_true")
    args = ap.parse_args()

    if args.category:
        cat = json.load(open(os.path.join(CACHE, args.brand, "catalog.json")))
        srcs = [c["path"] for c in cat["clips"] if c["category"] == args.category]
        out = args.out or os.path.join(CACHE, args.brand, "shots", args.category)
    else:
        srcs = args.files
        out = args.out or os.path.join(CACHE, args.brand or "misc", "shots", "custom")
    if not srcs:
        sys.exit("対象が無い")
    os.makedirs(out, exist_ok=True)

    plan, total_cuts = [], 0
    for p in srcs:
        segs, total = segments(p, args.thresh, args.min_dur, args.max_dur, args.cap)
        plan.append({"src": p, "name": os.path.basename(p), "total": round(total, 1),
                     "segs": segs})
        total_cuts += len(segs)
        print(f"  {os.path.basename(p)[:46]:48s} {total:7.1f}s → {len(segs):3d}カット",
              file=sys.stderr)
    if args.detect_only:
        print(json.dumps({"sources": len(plan), "cuts": total_cuts}, ensure_ascii=False))
        return

    tw = 240
    idx, shots = 0, []
    for pl in plan:
        sd = os.path.join(out, slug(pl["name"]))
        os.makedirs(sd, exist_ok=True)
        for s in pl["segs"]:
            idx += 1
            clip = os.path.join(sd, f"{idx:04d}.mp4")
            if not os.path.exists(clip):
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(s["start"]),
                                "-i", pl["src"], "-t", str(s["dur"]),
                                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                                "-pix_fmt", "yuv420p", "-an", clip],
                               capture_output=True, timeout=300)
            th = os.path.join(sd, f"{idx:04d}.jpg")
            if not os.path.exists(th):
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(s["dur"] / 2),
                                "-i", clip, "-frames:v", "1",
                                "-vf", f"scale={tw}:-2", "-q:v", "5", th],
                               capture_output=True, timeout=120)
            if os.path.exists(clip):
                shots.append({"idx": idx, "clip": clip, "thumb": th, "dur": s["dur"],
                              "start": s["start"], "src": pl["name"]})

    with open(os.path.join(out, "shots.json"), "w") as f:
        json.dump(shots, f, ensure_ascii=False, indent=1)

    per = args.cols * args.rows
    sdir = os.path.join(out, "sheets")
    os.makedirs(sdir, exist_ok=True)
    br = browser()
    have = [s for s in shots if os.path.exists(s["thumb"])]
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(math.ceil(len(have) / per)):
            chunk = have[i * per:(i + 1) * per]
            hp = os.path.join(tmp, f"s{i}.html")
            with open(hp, "w") as f:
                f.write(sheet_html(chunk, args.cols, tw))
            w = args.cols * (tw + 6) + 12
            h = math.ceil(len(chunk) / args.cols) * (tw * 16 // 9 + 46) + 20
            subprocess.run([br, "--headless", "--disable-gpu", "--hide-scrollbars",
                            f"--window-size={w},{h}",
                            f"--screenshot={os.path.join(sdir, f'sheet-{i + 1:02d}.png')}",
                            f"file://{hp}"], capture_output=True, timeout=300)

    print(json.dumps({"out": out, "shots": len(shots),
                      "sheets": math.ceil(len(have) / per)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
