#!/usr/bin/env python3
"""コンタクトシート生成。素材を「Claudeが目で見て仕分ける」ための道具。

各クリップから数フレーム抜き、ファイル名つきのタイル表にしてPNGにする。
1枚に複数クリップ入るので、まとめてReadして中身を判定できる。

使い方:
  python3 contact_sheet.py --index ~/.claude/skills/vsl/cache/silen/broll-index.json
  python3 contact_sheet.py --index <idx> --per-sheet 6 --frames 3 --only-unnamed
  python3 contact_sheet.py --files a.mp4 b.mp4 --out /tmp/sheets

出力: <outdir>/sheet-01.png … と sheets.json（どのシートに何が載ったか）
"""
import argparse, html, json, math, os, re, subprocess, sys, tempfile

BROWSERS = ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
TILE_W = 300


def browser():
    for b in BROWSERS:
        if os.path.exists(b):
            return b
    sys.exit("Brave も Chrome も見つからない")


def dur_of(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", p], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def frames(path, outdir, n):
    d = dur_of(path)
    if d <= 0:
        return []
    base = re.sub(r"[^\w.-]", "_", os.path.splitext(os.path.basename(path))[0])[:60]
    out = []
    for i in range(n):
        t = d * (i + 0.5) / n
        fp = os.path.join(outdir, f"{base}__{i}.jpg")
        if not os.path.exists(fp):
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", path,
                            "-frames:v", "1", "-vf", f"scale={TILE_W}:-2", "-q:v", "4", fp],
                           capture_output=True, timeout=120)
        if os.path.exists(fp):
            out.append(fp)
    return out


def sheet_html(rows, w):
    body = []
    for r in rows:
        imgs = "".join(f'<img src="file://{html.escape(p)}">' for p in r["frames"])
        body.append(f'<div class=row><div class=lbl>{html.escape(r["label"])}'
                    f'<span class=meta>{r["dur"]}s</span></div>'
                    f'<div class=imgs>{imgs}</div></div>')
    return f"""<!doctype html><meta charset=utf-8>
<style>
 html,body{{margin:0;background:#0d0d0d;color:#fff;
   font-family:-apple-system,"Hiragino Sans",sans-serif;width:{w}px}}
 .row{{border-bottom:1px solid #333;padding:6px 8px}}
 .lbl{{font-size:15px;font-weight:600;margin-bottom:4px;word-break:break-all}}
 .meta{{color:#8ac;font-weight:400;margin-left:8px;font-size:13px}}
 .imgs{{display:flex;gap:4px}} img{{height:200px;background:#000}}
</style>{''.join(body)}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index")
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--out", default=None)
    ap.add_argument("--per-sheet", type=int, default=6)
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--min-dur", type=float, default=0.0)
    args = ap.parse_args()

    clips = []
    if args.index:
        idx = json.load(open(args.index))
        outdir = args.out or os.path.join(os.path.dirname(args.index), "sheets")
        clips = [(c["path"], c["name"], c["duration"]) for c in idx["clips"]]
    else:
        outdir = args.out or tempfile.mkdtemp()
        clips = [(p, os.path.basename(p), round(dur_of(p), 2)) for p in args.files]
    clips = [c for c in clips if c[2] >= args.min_dur]

    fdir = os.path.join(outdir, "frames")
    os.makedirs(fdir, exist_ok=True)
    br = browser()

    rows = []
    for path, name, dur in clips:
        fr = frames(path, fdir, args.frames)
        if fr:
            rows.append({"label": name, "path": path, "dur": dur, "frames": fr})

    w = TILE_W * args.frames + 4 * (args.frames - 1) + 16
    sheets = []
    n_sheets = math.ceil(len(rows) / args.per_sheet)
    with tempfile.TemporaryDirectory() as tmp:
        for s in range(n_sheets):
            chunk = rows[s * args.per_sheet:(s + 1) * args.per_sheet]
            h = sum(232 for _ in chunk) + 20
            hp = os.path.join(tmp, f"s{s}.html")
            with open(hp, "w") as f:
                f.write(sheet_html(chunk, w))
            out = os.path.join(outdir, f"sheet-{s + 1:02d}.png")
            subprocess.run([br, "--headless", "--disable-gpu", "--hide-scrollbars",
                            f"--window-size={w},{h}", f"--screenshot={out}", f"file://{hp}"],
                           capture_output=True, timeout=180)
            sheets.append({"sheet": out, "clips": [c["path"] for c in chunk]})

    with open(os.path.join(outdir, "sheets.json"), "w") as f:
        json.dump(sheets, f, ensure_ascii=False, indent=1)
    print(json.dumps({"outdir": outdir, "sheets": len(sheets), "clips": len(rows)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
