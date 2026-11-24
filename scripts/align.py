#!/usr/bin/env python3
"""HeyGen等の完成ナレ音声を台本の行に割り付ける（強制アライメント）。

whisper.cpp で文字起こし＋トークン時刻を取り、**台本の文字列**と突き合わせて
各行の開始/終了秒を出す。文字起こしの誤字はここで捨てられる（正は台本側）。

前提: brew install whisper-cpp ＋ モデル ~/.cache/whisper/ggml-*.bin

使い方:
  python3 align.py <base.mp4|mp3> <shotlist.json>            # timeline.json を書く
  python3 align.py <base.mp4> <shotlist.json> --model <path>

出力: <shotlist と同じ場所>/timeline.json
  {"lines":[{"id":"L001","text":"…","start":0.42,"end":3.10,"conf":0.93}], "duration":312.4}
"""
import argparse, difflib, glob, json, os, re, subprocess, sys, tempfile

MODEL_DIRS = [os.path.expanduser("~/.cache/whisper"), os.path.expanduser("~/models")]
DROP = "、。「」『』（）()・…！？!?　 \n\r\t"


def find_model(explicit=None):
    if explicit:
        return explicit
    for d in MODEL_DIRS:
        got = sorted(glob.glob(os.path.join(d, "ggml-*.bin")))
        if got:                       # large > medium > small の順に大きいものを優先
            return max(got, key=os.path.getsize)
    sys.exit("whisperモデルが無い。~/.cache/whisper/ に ggml-*.bin を置く")


def to_wav(src, dst):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src,
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", dst],
                   check=True, capture_output=True)


def transcribe(wav, model):
    """whisper.cpp をトークン時刻つきで回し、(文字, 秒) の列を返す。"""
    out = wav + ".json"
    subprocess.run(["whisper-cli", "-m", model, "-f", wav, "-l", "ja",
                    "-oj", "-ojf", "-of", wav, "-np", "-pp"],
                   check=True, capture_output=True)
    if not os.path.exists(out):
        sys.exit("whisper-cli がJSONを出さなかった")
    data = json.load(open(out))

    chars = []
    for seg in data.get("transcription", []):
        toks = seg.get("tokens")
        if toks:
            for t in toks:
                txt = t.get("text", "")
                if txt.startswith("[") or not txt.strip():
                    continue
                off = t.get("offsets", {})
                s = off.get("from", 0) / 1000.0
                e = off.get("to", 0) / 1000.0
                for i, ch in enumerate(txt):
                    n = max(len(txt), 1)
                    chars.append((ch, s + (e - s) * i / n, s + (e - s) * (i + 1) / n))
        else:
            off = seg.get("offsets", {})
            s, e = off.get("from", 0) / 1000.0, off.get("to", 0) / 1000.0
            txt = seg.get("text", "")
            n = max(len(txt), 1)
            for i, ch in enumerate(txt):
                chars.append((ch, s + (e - s) * i / n, s + (e - s) * (i + 1) / n))
    return chars


def norm(s):
    return "".join(c for c in s if c not in DROP)


def align(script_lines, chars):
    """台本文字列 ↔ 文字起こし文字列 を対応づけ、行ごとの秒を返す。"""
    hyp_chars = [c for c, _, _ in chars]
    hyp_norm, hyp_map = [], []
    for i, c in enumerate(hyp_chars):
        if c not in DROP:
            hyp_norm.append(c)
            hyp_map.append(i)

    ref_norm, ref_owner = [], []
    for li, ln in enumerate(script_lines):
        for c in norm(ln["text"]):
            ref_norm.append(c)
            ref_owner.append(li)

    sm = difflib.SequenceMatcher(None, ref_norm, hyp_norm, autojunk=False)
    hit = {}                                    # ref index -> hyp index
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            hit[a + k] = b + k

    spans = {}
    for ri, hi in hit.items():
        li = ref_owner[ri]
        _, s, e = chars[hyp_map[hi]]
        cur = spans.get(li)
        spans[li] = (min(cur[0], s), max(cur[1], e), cur[2] + 1) if cur else (s, e, 1)

    out, prev_end = [], 0.0
    for li, ln in enumerate(script_lines):
        n_ref = sum(1 for o in ref_owner if o == li) or 1
        if li in spans:
            s, e, n = spans[li]
            conf = round(min(n / n_ref, 1.0), 2)
        else:                                    # 拾えなかった行は前後から補間
            s, e, conf = prev_end, prev_end, 0.0
        s = max(s, prev_end)
        e = max(e, s + 0.25)
        prev_end = e
        out.append({"id": ln["id"], "text": ln["text"],
                    "start": round(s, 3), "end": round(e, 3), "conf": conf})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("shotlist")
    ap.add_argument("--model")
    args = ap.parse_args()

    sl = json.load(open(args.shotlist))
    base = os.path.dirname(os.path.abspath(args.shotlist))
    lines = []
    for sc in sl["scenes"]:
        for i, ln in enumerate(sc.get("lines", []), 1):
            lines.append({"id": ln.get("id") or f"{sc['id']}-{i}", "text": ln["vo"]})
    if not lines:
        sys.exit("shotlist に行が無い")

    model = find_model(args.model)
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "a.wav")
        to_wav(args.audio, wav)
        chars = transcribe(wav, model)
    if not chars:
        sys.exit("文字起こしが空。音声トラックを確認する")

    timeline = align(lines, chars)
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", args.audio], capture_output=True, text=True)
    out = {"source": os.path.abspath(args.audio),
           "duration": round(float(dur.stdout.strip() or 0), 2),
           "model": os.path.basename(model), "lines": timeline}
    tp = os.path.join(base, "timeline.json")
    with open(tp, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    weak = [l["id"] for l in timeline if l["conf"] < 0.5]
    print(json.dumps({"timeline": tp, "lines": len(timeline),
                      "low_confidence": weak}, ensure_ascii=False))


if __name__ == "__main__":
    main()
