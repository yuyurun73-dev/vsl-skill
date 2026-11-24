#!/usr/bin/env python3
"""テロップPNGレンダラー（negirai/SILEN確定仕様）。
HTML → Brave headless → 透過PNG。ffmpegにdrawtext/libassが無いのでこの経路。

確定仕様（変更禁止・[[silen-telop-spec]]）:
  黒帯 60% / 太明朝W6 白＋黒縁 / 1帯1フレーズ / 縦位置は画面下寄りセンター
  強調 恐怖=赤 #E8121C ／ オファー=黄 #FFE600（光彩あり）

使い方:
  python3 render_telop.py spec.json

spec.json:
{
  "size": [1080, 1920],          # 省略時 1080x1920
  "y": 1000,                     # 帯の中心Y（省略時 height*0.52）
  "outdir": "/abs/telop",
  "items": [
    {"id": "S01-1", "text": "その<r>いびき</r>、ただの疲れやない"},
    {"id": "S01-2", "text": "今だけ<y>62%オフ</y>", "band": false}
  ]
}
- インラインタグ: <r>=赤(恐怖) <y>=黄(オファー)。それ以外はプレーンテキスト扱い。
- "band": false で黒帯なし（縁取りだけで抜く）
- 出力: <outdir>/<id>.png（透過・フルキャンバス。ffmpegで overlay=0:0 する前提）
"""
import html as htmlmod
import json, os, re, subprocess, sys, tempfile

BROWSERS = [
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]
RED = "#E8121C"
YELLOW = "#FFE600"


def browser():
    for b in BROWSERS:
        if os.path.exists(b):
            return b
    sys.exit("Brave も Chrome も見つからない")


def tokenize(text):
    """<r>/<y> を剥がして (文字, 色クラス or None) の列にする。他のタグは文字扱い。"""
    toks, cls, i = [], None, 0
    while i < len(text):
        m = re.match(r"</?([ry])>", text[i:])
        if m:
            cls = None if m.group(0).startswith("</") else m.group(1)
            i += m.end()
            continue
        toks.append((text[i], cls))
        i += 1
    return toks


def markup(toks):
    """トークン列 → HTML（同じ色が続く分はまとめる）。"""
    out, cur, buf = [], "sentinel", []

    def flush():
        if not buf:
            return
        s = htmlmod.escape("".join(buf)).replace("\n", "<br>")
        out.append(f'<span class="{cur}">{s}</span>' if cur else s)
        buf.clear()

    for ch, cls in toks:
        if cls != cur:
            flush()
            cur = cls
        buf.append(ch)
    flush()
    return "".join(out)


def page(toks, w, h, y, band, fs):
    return f"""<!doctype html><meta charset=utf-8>
<style>
  html,body{{margin:0;padding:0;width:{w}px;height:{h}px;background:transparent;overflow:hidden}}
  .wrap{{position:absolute;left:0;top:{y}px;transform:translateY(-50%);
         width:{w}px;display:flex;justify-content:center}}
  .band{{{'background:rgba(0,0,0,.60);' if band else ''}
         padding:{int(fs*0.34)}px {int(fs*0.55)}px;max-width:{int(w*0.92)}px;box-sizing:border-box}}
  .t{{font-family:"Hiragino Mincho ProN","Toppan Bunkyu Midashi Mincho",serif;
      font-weight:600;font-size:{fs:.1f}px;line-height:1.32;color:#fff;text-align:center;
      letter-spacing:.01em;white-space:pre;
      -webkit-text-stroke:{max(3, int(fs*0.055))}px #000;paint-order:stroke fill;
      text-shadow:0 {int(fs*0.05)}px {int(fs*0.13)}px rgba(0,0,0,.85)}}
  .r{{color:{RED};text-shadow:0 0 {int(fs*0.30)}px rgba(232,18,28,.75),0 {int(fs*0.05)}px {int(fs*0.13)}px rgba(0,0,0,.9)}}
  .y{{color:{YELLOW};text-shadow:0 0 {int(fs*0.30)}px rgba(255,230,0,.70),0 {int(fs*0.05)}px {int(fs*0.13)}px rgba(0,0,0,.9)}}
</style>
<div class=wrap><div class=band><div class=t>{markup(toks)}</div></div></div>"""


def em(toks):
    """全角=1.0em / 半角=0.55em で行幅を見積もる。"""
    return sum(0.55 if ord(c) < 0x2E80 else 1.0 for c, _ in toks)


PUNCT = "、。／/ 　!?！？…"
PARTICLE = "はがをにでともやのへ"          # この直後は切ってよい
NO_HEAD = "ぁぃぅぇぉっゃゅょーん、。）」』"  # 行頭に来てはいけない


def is_kanji(c):
    return 0x4E00 <= ord(c) <= 0x9FFF


def split_two(toks):
    """中央付近の日本語の切れ目で2行に割る。句読点＞助詞の後＞漢字の前 の順で優先。"""
    n = len(toks)
    mid = n / 2
    best, best_score = None, 1e9
    for i in range(max(2, int(n * 0.25)), min(n - 1, int(n * 0.75)) + 1):
        prev, nxt = toks[i - 1][0], toks[i][0]
        if nxt in NO_HEAD:
            continue
        bonus = 0
        if prev in PUNCT:
            bonus += 6
        elif prev in PARTICLE:
            bonus += 3
        if is_kanji(nxt):
            bonus += 2
        score = abs(i - mid) - bonus
        if score < best_score:
            best, best_score = i, score
    if best is None:
        best = int(round(mid))
    a = [t for t in toks[:best] if t[0] not in " 　"] or toks[:best]
    b = toks[best:]
    while b and b[0][0] in " 　":
        b = b[1:]
    return a, b


def layout(text, w):
    """トークン列（改行入り）とフォントサイズを返す。
    1帯1フレーズが原則なので、まず1行に収める。潰れすぎるなら2行に割る。"""
    max_fs, min_fs = w * 0.085, w * 0.048

    def fs_for(em_width):
        # padding は左右 0.55em ずつ → 使える幅 = fs*em_width + 1.1*fs
        # 0.88 は安全マージン。0.92 だと letter-spacing と縁取りの分だけ端が切れる
        return w * 0.88 / (em_width + 1.1)

    toks = tokenize(text)
    if any(c == "\n" for c, _ in toks):               # 明示改行は尊重する
        lines, cur = [], []
        for t in toks:
            if t[0] == "\n":
                lines.append(cur)
                cur = []
            else:
                cur.append(t)
        lines.append(cur)
        widest = max((em(l) for l in lines), default=1)
        return toks, max(min_fs * 0.7, min(max_fs, fs_for(widest)))

    fs = fs_for(em(toks))
    if fs >= min_fs:
        return toks, min(fs, max_fs)

    a, b = split_two(toks)
    return a + [("\n", None)] + b, max(min_fs * 0.72,
                                       min(fs_for(max(em(a), em(b))), max_fs))


def edge_bleed(png, w, margin=5):
    """左右の端に不透明な画素があれば「文字が切れている」と判定する。

    帯は中央寄せで幅に余白を持たせる設計なので、端まで色が届いていたら
    フォントサイズの見積もりが甘かったということ。
    """
    for x in (0, w - margin):
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", png,
             "-vf", f"crop={margin}:ih:{x}:0,alphaextract,signalstats,"
                    f"metadata=print:key=lavfi.signalstats.YMAX",
             "-f", "null", "-"], capture_output=True, text=True)
        m = re.search(r"YMAX=(\d+)", r.stderr + r.stdout)
        if m and int(m.group(1)) > 12:
            return True
    return False


def main():
    spec = json.load(open(sys.argv[1]))
    w, h = spec.get("size", [1080, 1920])
    y = spec.get("y", int(h * 0.52))
    outdir = spec["outdir"]
    os.makedirs(outdir, exist_ok=True)
    br = browser()
    made = []
    with tempfile.TemporaryDirectory() as tmp:
        for it in spec["items"]:
            out = os.path.join(outdir, f"{it['id']}.png")
            toks, fs = layout(it["text"], w)
            if it.get("font_size"):
                fs = it["font_size"]
            hp = os.path.join(tmp, f"{it['id']}.html")
            with open(hp, "w") as f:
                f.write(page(toks, w, h, it.get("y", y), it.get("band", True), fs))
            subprocess.run([br, "--headless", "--disable-gpu", "--hide-scrollbars",
                            "--default-background-color=00000000",
                            f"--window-size={w},{h}", f"--screenshot={out}", f"file://{hp}"],
                           capture_output=True, timeout=120)
            if not os.path.exists(out):
                sys.exit(f"レンダー失敗: {it['id']}")
            made.append(out)

    # 端の切れ検査は1枚あたりffmpeg2回かかるので既定では走らせない。
    # レイアウトを触ったときだけ --check で全数確認する。
    bleed = ([os.path.basename(p)[:-4] for p in made if edge_bleed(p, w)]
             if "--check" in sys.argv else [])
    print(json.dumps({"outdir": outdir, "count": len(made), "edge_bleed": bleed},
                     ensure_ascii=False))
    if bleed:
        sys.stderr.write("⚠ 端で文字が切れている帯: " + ", ".join(bleed) + "\n")


if __name__ == "__main__":
    main()
