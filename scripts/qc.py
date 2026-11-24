#!/usr/bin/env python3
"""納品前QC。フレーム抜き出し＋音声チェック。

Claude自身が目視するためのツール。出力されたjpgをReadして
①化け文字 ②顔ブレ ③テロップの見切れ を確認する。
音声は無音区間・音量・尺で機械チェックする。

使い方:
  python3 qc.py <mp4 or dir> --n 8            # フレーム抜き（デフォルト8枚）
  python3 qc.py <mp4> --n 12 --audio          # 音声チェックも
  python3 qc.py <dir> --gallery --open        # クリップ群を一覧HTMLで

出力: <対象と同階層>/_qc/ に jpg と index.html
"""
import argparse, glob, html, json, os, re, subprocess, sys

VIDEO_EXT = (".mp4", ".mov", ".m4v")


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
    base = re.sub(r"[^\w.-]", "_", os.path.splitext(os.path.basename(path))[0])
    made = []
    for i in range(n):
        t = d * (i + 0.5) / n
        out = os.path.join(outdir, f"{base}_{i:02d}.jpg")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", path,
                        "-frames:v", "1", "-vf", "scale=420:-2", "-q:v", "4", out],
                       capture_output=True, timeout=120)
        if os.path.exists(out):
            made.append((out, round(t, 2)))
    return made


def audio_check(path):
    """無音区間・ラウドネス・音声トラック有無。TTSの生成事故を機械で拾う。"""
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", path, "-af",
                        "silencedetect=noise=-45dB:d=1.2,ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    log = r.stderr
    sil = []
    for m in re.finditer(r"silence_start: ([\d.]+)", log):
        sil.append(float(m.group(1)))
    ends = [float(m.group(1)) for m in re.finditer(r"silence_end: ([\d.]+)", log)]
    lufs = re.findall(r"I:\s*(-?[\d.]+) LUFS", log)
    has_audio = "Audio:" in log
    gaps = [{"start": s, "end": e, "len": round(e - s, 2)}
            for s, e in zip(sil, ends) if e - s >= 1.2]
    return {"has_audio": has_audio,
            "lufs": float(lufs[-1]) if lufs else None,
            "long_silences": gaps,
            "duration": round(dur_of(path), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--audio", action="store_true")
    ap.add_argument("--gallery", action="store_true")
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()

    if os.path.isdir(args.target):
        vids = sorted(p for p in glob.glob(os.path.join(args.target, "*"))
                      if p.lower().endswith(VIDEO_EXT))
        root = args.target
    else:
        vids = [args.target]
        root = os.path.dirname(os.path.abspath(args.target))
    if not vids:
        sys.exit("動画が無い")

    outdir = os.path.join(root, "_qc")
    os.makedirs(outdir, exist_ok=True)

    report = []
    for v in vids:
        fr = frames(v, outdir, args.n)
        entry = {"file": v, "frames": [f for f, _ in fr]}
        if args.audio:
            entry["audio"] = audio_check(v)
        report.append(entry)

    if args.gallery or len(vids) > 1:
        secs = []
        for e in report:
            imgs = "".join(f'<img src="{html.escape(p)}" loading="lazy">' for p in e["frames"])
            a = e.get("audio")
            note = ""
            if a:
                warn = []
                if not a["has_audio"]:
                    warn.append("音声トラック無し")
                if a["long_silences"]:
                    warn.append(f"長い無音{len(a['long_silences'])}箇所")
                note = (f'<div class=meta>{a["duration"]}s / {a["lufs"]} LUFS'
                        + (f' / <b class=w>{"・".join(warn)}</b>' if warn else "") + "</div>")
            secs.append(f'<section><h2>{html.escape(os.path.basename(e["file"]))}</h2>'
                        f'{note}<div class=row>{imgs}</div></section>')
        page = f"""<!doctype html><meta charset=utf-8><title>QC</title>
<style>body{{background:#101010;color:#eee;font-family:-apple-system,sans-serif;padding:20px}}
h2{{font-size:15px;margin:22px 0 6px}} .meta{{color:#999;font-size:12px;margin-bottom:6px}}
.w{{color:#ff6b6b}} .row{{display:flex;gap:6px;overflow-x:auto;padding-bottom:6px}}
img{{height:300px;border-radius:4px;background:#000}}</style>
<h1 style="font-size:18px">QC — {len(report)}本</h1>{''.join(secs)}"""
        gp = os.path.join(outdir, "index.html")
        with open(gp, "w") as f:
            f.write(page)
        report_out = {"gallery": gp, "items": report}
        if args.open:
            subprocess.run(["open", gp])
    else:
        report_out = report[0]

    print(json.dumps(report_out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
