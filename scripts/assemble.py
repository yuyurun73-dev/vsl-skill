#!/usr/bin/env python3
"""VSL組み立て（クリップ＋VO＋テロップ → 完パケmp4）。

**VO（ナレ音声）が尺のマスター**。1行=1TTSチャンク=1テロップ帯にしてあるので、
各行の音声長をffprobeで測ればテロップの表示区間が自動で決まる（whisper不要）。
映像は行の合計尺にトリム/ループして合わせる。

使い方:
  python3 assemble.py <project_dir>/manifest.json
  python3 assemble.py manifest.json --only S03      # そのシーンだけ作り直す
  python3 assemble.py manifest.json --no-concat     # シーンmp4まで

manifest.json（相対パスは manifest のあるディレクトリ基準）:
{
  "name": "silen-oxygen-v4",
  "size": [1080, 1920],
  "fps": 30,
  "scenes": [
    {"id": "S01",
     "video": "clips/S01.mp4",
     "video_start": 0,               # 素材の使い始め秒（省略可）
     "keep_source_audio": false,     # trueで素材の環境音を薄く残す
     "source_audio_db": -18,
     "lines": [
       {"id": "S01-1", "audio": "vo/S01-1.mp3", "telop": "telop/S01-1.png", "gap": 0.25}
     ]},
    {"id": "S02", "video": "clips/S02.mp4", "dur": 3.0, "lines": []}   # 無声Bロール
  ],
  "bgm": {"path": "bgm.mp3", "db": -26},
  "endcard": {"image": "cta.png", "dur": 3.0}
}
"""
import argparse, json, os, subprocess, sys

DEFAULT_GAP = 0.22


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(" ".join(cmd[:12]) + " ...\n" + r.stderr[-2500:] + "\n")
        raise SystemExit(f"ffmpeg失敗 (exit {r.returncode})")
    return r


def dur_of(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise SystemExit(f"尺が取れない: {path}")


def build_scene(sc, base, size, fps, scenes_dir):
    w, h = size
    sid = sc["id"]
    out = os.path.join(scenes_dir, f"{sid}.mp4")

    lines, t = [], 0.0
    for ln in sc.get("lines", []):
        ap = os.path.join(base, ln["audio"])
        d = dur_of(ap)
        gap = ln.get("gap", DEFAULT_GAP)
        lines.append({"audio": ap, "telop": ln.get("telop"), "start": t, "end": t + d})
        t += d + gap
    total = round(sc.get("dur") or t or 3.0, 3)

    inputs, filt = [], []
    vid = os.path.join(base, sc["video"])
    if sc.get("video_start"):
        inputs += ["-ss", str(sc["video_start"])]
    inputs += ["-stream_loop", "-1", "-i", vid]

    ai = []
    for ln in lines:
        ai.append(len(ai) + 1)
        inputs += ["-i", ln["audio"]]

    ti = []
    for ln in lines:
        if ln["telop"]:
            tp = os.path.join(base, ln["telop"])
            ti.append((len(ai) + len(ti) + 1, ln))
            inputs += ["-i", tp]

    # zoom＋anchorで、素材に焼き込まれた字幕やワイプを画面外に追い出す
    z = sc.get("zoom", 1.0)
    anchor = sc.get("anchor", "center")
    ax = {"left": "0", "right": "in_w-out_w"}.get(anchor, "(in_w-out_w)/2")
    ay = {"top": "0", "bottom": "in_h-out_h"}.get(anchor, "(in_h-out_h)/2")
    filt.append(f"[0:v]scale={int(w * z)}:{int(h * z)}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h}:{ax}:{ay},fps={fps},setsar=1,format=yuv420p,"
                f"trim=0:{total},setpts=PTS-STARTPTS[v0]")
    cur = "v0"
    for n, (idx, ln) in enumerate(ti, 1):
        filt.append(f"[{idx}:v]scale={w}:{h}[t{n}]")
        filt.append(f"[{cur}][t{n}]overlay=0:0:enable='between(t,{ln['start']:.3f},"
                    f"{ln['end']:.3f})'[v{n}]")
        cur = f"v{n}"

    if lines:
        for n in range(len(lines)):
            ms = int(lines[n]["start"] * 1000)
            filt.append(f"[{ai[n]}:a]aresample=48000,aformat=channel_layouts=stereo,"
                        f"adelay={ms}|{ms}[a{n}]")
        mix = "".join(f"[a{n}]" for n in range(len(lines)))
        if sc.get("keep_source_audio"):
            db = sc.get("source_audio_db", -18)
            filt.append(f"[0:a]aresample=48000,aformat=channel_layouts=stereo,"
                        f"volume={db}dB,atrim=0:{total},asetpts=PTS-STARTPTS[src]")
            mix += "[src]"
            n_mix = len(lines) + 1
        else:
            n_mix = len(lines)
        if n_mix == 1:
            filt.append(f"{mix}anull[aout_raw]")  # 1本だけならミックス不要
        else:
            filt.append(f"{mix}amix=inputs={n_mix}:normalize=0:dropout_transition=0[aout_raw]")
        filt.append(f"[aout_raw]apad,atrim=0:{total},asetpts=PTS-STARTPTS[aout]")
        amap = ["-map", "[aout]"]
    else:
        inputs += ["-f", "lavfi", "-t", str(total),
                   "-i", "anullsrc=r=48000:cl=stereo"]  # 無声Bロール用の無音トラック
        amap = ["-map", f"{len(ai) + len(ti) + 1}:a"]

    cmd = (["ffmpeg", "-y", "-v", "error"] + inputs +
           ["-filter_complex", ";".join(filt), "-map", f"[{cur}]"] + amap +
           ["-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
            "-r", str(fps), "-c:a", "aac", "-ar", "48000", "-b:a", "192k",
            "-t", str(total), "-movflags", "+faststart", out])
    sh(cmd)
    return out, total


def build_endcard(ec, base, size, fps, scenes_dir):
    w, h = size
    out = os.path.join(scenes_dir, "ZZ_endcard.mp4")
    d = ec.get("dur", 3.0)
    sh(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", str(d),
        "-i", os.path.join(base, ec["image"]),
        "-f", "lavfi", "-t", str(d), "-i", "anullsrc=r=48000:cl=stereo",
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
               f"fps={fps},setsar=1,format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", "-b:a", "192k", "-movflags", "+faststart", out])
    return out, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--only", help="このシーンIDだけ作り直す")
    ap.add_argument("--force", action="store_true", help="全シーンを作り直す")
    ap.add_argument("--no-concat", action="store_true")
    args = ap.parse_args()

    mf = json.load(open(args.manifest))
    base = os.path.dirname(os.path.abspath(args.manifest))
    size = mf.get("size", [1080, 1920])
    fps = mf.get("fps", 30)
    scenes_dir = os.path.join(base, "scenes")
    os.makedirs(scenes_dir, exist_ok=True)

    parts, total = [], 0.0
    for sc in mf["scenes"]:
        path = os.path.join(scenes_dir, f"{sc['id']}.mp4")
        # 出来ているシーンは作り直さない。直したいシーンはmp4を消すか --only で指す
        stale = args.only == sc["id"] or args.force
        if os.path.exists(path) and not stale:
            parts.append((path, dur_of(path)))
            continue
        p, d = build_scene(sc, base, size, fps, scenes_dir)
        print(f"  {sc['id']}  {d:.2f}s", file=sys.stderr)
        parts.append((p, d))
    if mf.get("endcard"):
        parts.append(build_endcard(mf["endcard"], base, size, fps, scenes_dir))
    total = sum(d for _, d in parts)

    if args.no_concat:
        print(json.dumps({"scenes": [p for p, _ in parts], "total": round(total, 2)},
                         ensure_ascii=False))
        return

    lst = os.path.join(scenes_dir, "concat.txt")
    with open(lst, "w") as f:
        for p, _ in parts:
            f.write(f"file '{p}'\n")
    joined = os.path.join(base, f"{mf.get('name', 'vsl')}.mp4")
    sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
        "-c", "copy", "-movflags", "+faststart", joined])

    if mf.get("bgm"):
        bgm = mf["bgm"]
        mixed = os.path.join(base, f"{mf.get('name', 'vsl')}-bgm.mp4")
        sh(["ffmpeg", "-y", "-v", "error", "-i", joined,
            "-stream_loop", "-1", "-i", os.path.join(base, bgm["path"]),
            "-filter_complex",
            f"[1:a]aresample=48000,volume={bgm.get('db', -26)}dB[b];"
            f"[0:a][b]amix=inputs=2:normalize=0:duration=first[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", mixed])
        os.replace(mixed, joined)

    if mf.get("loudnorm", True):     # 広告出稿向けに -14 LUFS へ揃える
        norm = os.path.join(base, f"{mf.get('name', 'vsl')}-ln.mp4")
        sh(["ffmpeg", "-y", "-v", "error", "-i", joined,
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-b:a", "192k",
            "-movflags", "+faststart", norm])
        os.replace(norm, joined)

    print(json.dumps({"out": joined, "total": round(total, 2),
                      "scenes": len(parts)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
