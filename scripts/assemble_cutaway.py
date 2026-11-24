#!/usr/bin/env python3
"""HeyGenアバター版の組み立て（ベース動画 ＋ Bロールの差し込み ＋ テロップ）。

ベース＝喋っているアバター動画。**その音声には一切触らない**（尺のマスター）。
Bロールは指定区間だけ映像を上から被せる（＝カットアウェイ）。テロップは最後に焼く。

使い方:
  python3 assemble_cutaway.py <proj>/manifest_cutaway.json

manifest_cutaway.json:
{
  "name": "silen-oxygen-v4",
  "size": [1080, 1920], "fps": 30,
  "base": "base/heygen.mp4",
  "cutaways": [{"start": 12.4, "end": 18.0, "video": "/abs/Broll17.mp4", "in": 0.0}],
  "telop":    [{"start": 0.4, "end": 3.1, "png": "telop/S01-1.png"}],
  "endcard":  {"image": "cta.png", "dur": 3.0},
  "loudnorm": true
}
"""
import argparse, json, os, subprocess, sys

CUT_BATCH = 8        # 1パスあたりの差し込み数
TELOP_BATCH = 20     # 1パスあたりのテロップ数


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(" ".join(cmd[:10]) + " ...\n" + r.stderr[-2500:] + "\n")
        raise SystemExit(f"ffmpeg失敗 (exit {r.returncode})")


def dur_of(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", p], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def vfit(idx, w, h, fps):
    return (f"[{idx}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},fps={fps},setsar=1")


def pass_cutaways(src, items, base_dir, w, h, fps, out):
    """差し込みを最大CUT_BATCH本ずつ焼く。音声はコピーで素通し。"""
    inputs, filt = ["-i", src], []
    cur = "v0"
    filt.append(f"{vfit(0, w, h, fps)},format=yuv420p[v0]")
    for n, c in enumerate(items, 1):
        path = c["video"] if os.path.isabs(c["video"]) else os.path.join(base_dir, c["video"])
        length = c["end"] - c["start"]
        src_in = c.get("in", 0.0)
        if dur_of(path) - src_in < length:   # 素材が短ければループで埋める
            inputs += ["-stream_loop", "-1"]
        inputs += ["-i", path]
        filt.append(f"{vfit(n, w, h, fps)},trim={src_in}:{src_in + length},"
                    f"setpts=PTS-STARTPTS+{c['start']}/TB[c{n}]")
        filt.append(f"[{cur}][c{n}]overlay=0:0:enable='between(t,{c['start']:.3f},"
                    f"{c['end']:.3f})'[v{n}]")
        cur = f"v{n}"
    sh(["ffmpeg", "-y", "-v", "error"] + inputs +
       ["-filter_complex", ";".join(filt), "-map", f"[{cur}]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-r", str(fps), "-c:a", "copy", "-movflags", "+faststart", out])


def pass_telop(src, items, base_dir, w, h, out):
    inputs, filt = ["-i", src], []
    cur = "0:v"
    for n, t in enumerate(items, 1):
        png = t["png"] if os.path.isabs(t["png"]) else os.path.join(base_dir, t["png"])
        inputs += ["-i", png]
        filt.append(f"[{n}:v]scale={w}:{h}[t{n}]")
        filt.append(f"[{cur}][t{n}]overlay=0:0:enable='between(t,{t['start']:.3f},"
                    f"{t['end']:.3f})'[v{n}]")
        cur = f"v{n}"
    sh(["ffmpeg", "-y", "-v", "error"] + inputs +
       ["-filter_complex", ";".join(filt), "-map", f"[{cur}]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", out])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    args = ap.parse_args()
    mf = json.load(open(args.manifest))
    base = os.path.dirname(os.path.abspath(args.manifest))
    w, h = mf.get("size", [1080, 1920])
    fps = mf.get("fps", 30)
    work = os.path.join(base, "work")
    os.makedirs(work, exist_ok=True)

    src = mf["base"] if os.path.isabs(mf["base"]) else os.path.join(base, mf["base"])
    if not os.path.exists(src):
        sys.exit(f"ベース動画が無い: {src}")

    cuts = sorted(mf.get("cutaways", []), key=lambda c: c["start"])
    cur = src
    for i in range(0, len(cuts), CUT_BATCH):
        out = os.path.join(work, f"cut{i // CUT_BATCH}.mp4")
        pass_cutaways(cur, cuts[i:i + CUT_BATCH], base, w, h, fps, out)
        print(f"  差し込み {i + 1}-{min(i + CUT_BATCH, len(cuts))} / {len(cuts)}",
              file=sys.stderr)
        cur = out
    if not cuts:                       # 差し込みが無くてもサイズは揃える
        out = os.path.join(work, "cut0.mp4")
        pass_cutaways(cur, [], base, w, h, fps, out)
        cur = out

    tel = sorted(mf.get("telop", []), key=lambda t: t["start"])
    for i in range(0, len(tel), TELOP_BATCH):
        out = os.path.join(work, f"tel{i // TELOP_BATCH}.mp4")
        pass_telop(cur, tel[i:i + TELOP_BATCH], base, w, h, out)
        print(f"  テロップ {i + 1}-{min(i + TELOP_BATCH, len(tel))} / {len(tel)}",
              file=sys.stderr)
        cur = out

    final = os.path.join(base, f"{mf.get('name', 'vsl')}.mp4")

    if mf.get("endcard"):
        ec = mf["endcard"]
        ecp = os.path.join(work, "endcard.mp4")
        img = ec["image"] if os.path.isabs(ec["image"]) else os.path.join(base, ec["image"])
        d = ec.get("dur", 3.0)
        sh(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", str(d), "-i", img,
            "-f", "lavfi", "-t", str(d), "-i", "anullsrc=r=48000:cl=stereo",
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                   f"fps={fps},setsar=1,format=yuv420p",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-b:a", "192k", ecp])
        norm = os.path.join(work, "body_norm.mp4")   # 音声形式を揃えてから連結する
        sh(["ffmpeg", "-y", "-v", "error", "-i", cur, "-c:v", "copy",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k", norm])
        lst = os.path.join(work, "concat.txt")
        with open(lst, "w") as f:
            f.write(f"file '{norm}'\nfile '{ecp}'\n")
        sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
            "-c", "copy", "-movflags", "+faststart", final])
    else:
        sh(["ffmpeg", "-y", "-v", "error", "-i", cur, "-c", "copy",
            "-movflags", "+faststart", final])

    if mf.get("loudnorm", True):
        ln = os.path.join(work, "ln.mp4")
        sh(["ffmpeg", "-y", "-v", "error", "-i", final,
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:v", "copy",
            "-c:a", "aac", "-ar", "48000", "-b:a", "192k", "-movflags", "+faststart", ln])
        os.replace(ln, final)

    print(json.dumps({"out": final, "duration": round(dur_of(final), 2),
                      "cutaways": len(cuts), "telop": len(tel)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
