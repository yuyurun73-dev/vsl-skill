#!/usr/bin/env python3
"""Bロール在庫インデクサ。
素材フォルダを走査して broll-index.json ＋ 一覧ギャラリーHTML を作る。
新規生成にクレジットを使う前に「在庫にあるか」を必ずここで確認するためのもの。

使い方:
  python3 index_broll.py "/Users/u/Desktop/silen material 2" --brand silen
  python3 index_broll.py <dir> --brand silen --open      # ギャラリーを開く

出力:
  ~/.claude/skills/vsl/cache/<brand>/broll-index.json   全クリップのメタ
  ~/.claude/skills/vsl/cache/<brand>/thumbs/*.jpg       中間フレーム
  ~/.claude/skills/vsl/cache/<brand>/gallery.html       目視用
"""
import argparse, html, json, os, subprocess, sys

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
CACHE_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")


def probe(path):
    """ffprobeで尺・解像度・音声有無を取る。取れなければNone。"""
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", path]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
        info = json.loads(out)
    except Exception:
        return None
    fmt = info.get("format", {})
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    dur = float(fmt.get("duration") or (v or {}).get("duration") or 0)
    return {
        "duration": round(dur, 2),
        "width": (v or {}).get("width"),
        "height": (v or {}).get("height"),
        "has_audio": a is not None,
    }


def thumb(path, dest, at):
    if os.path.exists(dest):
        return True
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", path,
           "-frames:v", "1", "-vf", "scale=360:-2", dest]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120)
    except Exception:
        return False
    return os.path.exists(dest)


def aspect_label(w, h):
    if not w or not h:
        return "?"
    r = w / h
    for label, val in (("9:16", 9 / 16), ("1:1", 1.0), ("4:5", 0.8), ("16:9", 16 / 9)):
        if abs(r - val) < 0.06:
            return label
    return f"{w}x{h}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+", help="素材フォルダ（複数可）")
    ap.add_argument("--brand", required=True)
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()

    out_dir = os.path.join(CACHE_ROOT, args.brand)
    thumbs = os.path.join(out_dir, "thumbs")
    os.makedirs(thumbs, exist_ok=True)

    clips, audios, images = [], [], []
    for root_dir in args.dirs:
        for root, _dirs, files in os.walk(root_dir):
            for fn in sorted(files):
                if fn.startswith("."):
                    continue
                path = os.path.join(root, fn)
                ext = os.path.splitext(fn)[1].lower()
                rel = os.path.relpath(path, root_dir)
                if ext in VIDEO_EXT:
                    meta = probe(path)
                    if not meta or meta["duration"] <= 0:
                        continue
                    key = str(abs(hash(path)))[:12] + ".jpg"
                    tp = os.path.join(thumbs, key)
                    thumb(path, tp, min(meta["duration"] / 2, meta["duration"] - 0.1))
                    clips.append({"path": path, "rel": rel, "name": fn,
                                  "thumb": tp, "aspect": aspect_label(meta["width"], meta["height"]),
                                  **meta})
                elif ext in AUDIO_EXT:
                    meta = probe(path) or {}
                    audios.append({"path": path, "rel": rel, "name": fn,
                                   "duration": meta.get("duration", 0)})
                elif ext in IMAGE_EXT:
                    images.append({"path": path, "rel": rel, "name": fn})

    index = {"brand": args.brand, "roots": args.dirs,
             "clips": clips, "audio": audios, "images": images}
    idx_path = os.path.join(out_dir, "broll-index.json")
    with open(idx_path, "w") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)

    cards = []
    for c in clips:
        cards.append(
            f'<figure><img src="{html.escape(c["thumb"])}" loading="lazy">'
            f'<figcaption><b>{html.escape(c["name"])}</b><br>'
            f'{c["duration"]}s / {c["aspect"]}{" / 音あり" if c["has_audio"] else ""}<br>'
            f'<code>{html.escape(c["rel"])}</code></figcaption></figure>')
    gal = f"""<!doctype html><meta charset=utf-8><title>{html.escape(args.brand)} Bロール在庫</title>
<style>
body{{background:#111;color:#eee;font-family:-apple-system,sans-serif;padding:24px}}
h1{{font-size:20px}} .n{{color:#888;font-size:13px;margin-bottom:20px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px}}
figure{{margin:0;background:#1c1c1c;border-radius:8px;overflow:hidden}}
img{{width:100%;display:block;background:#000}}
figcaption{{padding:8px 10px;font-size:12px;line-height:1.5}}
code{{color:#7aa;font-size:10px;word-break:break-all}}
</style>
<h1>{html.escape(args.brand)} Bロール在庫</h1>
<div class=n>動画 {len(clips)} / 音声 {len(audios)} / 画像 {len(images)}　—　新規生成の前にここから引く</div>
<div class=grid>{''.join(cards)}</div>"""
    gal_path = os.path.join(out_dir, "gallery.html")
    with open(gal_path, "w") as f:
        f.write(gal)

    print(json.dumps({"index": idx_path, "gallery": gal_path,
                      "clips": len(clips), "audio": len(audios), "images": len(images)},
                     ensure_ascii=False))
    if args.open:
        subprocess.run(["open", gal_path])


if __name__ == "__main__":
    main()
