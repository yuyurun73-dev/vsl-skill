#!/usr/bin/env python3
"""在庫にカテゴリーを付ける。

broll-index.json ＋ catalog-rules.json（ファイル名の正規表現 → カテゴリー）から
catalog.json と catalog.html を作る。素材が増えたらルールに1行足すだけでいい。

使い方:
  python3 categorize.py --brand silen [--open]

catalog-rules.json:
{
 "categories": {"symptom_night": {"label":"症状・夜", "desc":"…"} , …},
 "rules": [
   {"match":"^Broll01_", "category":"symptom_night", "tags":["夫","寝室"],
    "desc":"いびき本人アップ・夜", "caution":"（任意）使う時に潰すべき問題"}
 ],
 "default": {"category":"unsorted"}
}
"""
import argparse, html, json, os, re, subprocess, sys

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()

    d = os.path.join(CACHE, args.brand)
    idx = json.load(open(os.path.join(d, "broll-index.json")))
    rules_path = os.path.join(d, "catalog-rules.json")
    if not os.path.exists(rules_path):
        sys.exit(f"ルールが無い: {rules_path}")
    rules = json.load(open(rules_path))

    compiled = [(re.compile(r["match"]), r) for r in rules["rules"]]
    out = []
    for c in idx["clips"]:
        hit = None
        for rx, r in compiled:
            if rx.search(c["name"]):
                hit = r
                break
        r = hit or rules.get("default", {"category": "unsorted"})
        out.append({**c, "category": r["category"], "tags": r.get("tags", []),
                    "caution": r.get("caution", ""), "desc": r.get("desc", "")})

    cats = rules["categories"]
    order = list(cats.keys()) + ["unsorted"]
    out.sort(key=lambda x: (order.index(x["category"]) if x["category"] in order else 999,
                            x["name"]))

    catalog = {"brand": args.brand, "categories": cats, "clips": out,
               "counts": {k: sum(1 for x in out if x["category"] == k) for k in order}}
    cp = os.path.join(d, "catalog.json")
    with open(cp, "w") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=1)

    secs = []
    for k in order:
        items = [x for x in out if x["category"] == k]
        if not items:
            continue
        meta = cats.get(k, {"label": "未分類", "desc": "見て仕分ける"})
        cards = []
        for x in items:
            warn = (f'<div class=ng>{html.escape(x["caution"])}</div>'
                    if x["caution"] else "")
            cards.append(
                f'<figure><img src="{html.escape(x["thumb"])}" loading="lazy">{warn}'
                f'<figcaption><b>{html.escape(x["name"])}</b><br>'
                f'<span class=d>{html.escape(x["desc"])}</span><br>'
                f'{x["duration"]}s / {x["aspect"]}'
                f'{" / 音あり" if x["has_audio"] else ""}<br>'
                f'<span class=tag>{html.escape(" ".join(x["tags"]))}</span>'
                f'</figcaption></figure>')
        secs.append(f'<h2>{html.escape(meta["label"])} <span class=n>{len(items)}</span></h2>'
                    f'<p class=desc>{html.escape(meta.get("desc", ""))}</p>'
                    f'<div class=grid>{"".join(cards)}</div>')

    page = f"""<!doctype html><meta charset=utf-8><title>{html.escape(args.brand)} 素材カタログ</title>
<style>
body{{background:#0e0e0e;color:#eee;font-family:-apple-system,"Hiragino Sans",sans-serif;padding:26px;max-width:1500px;margin:auto}}
h1{{font-size:22px}} h2{{font-size:17px;margin:32px 0 2px;border-left:4px solid #4a9;padding-left:10px}}
.n{{color:#666;font-size:13px}} .desc{{color:#888;font-size:13px;margin:2px 0 12px 14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px}}
figure{{margin:0;background:#1a1a1a;border-radius:8px;overflow:hidden;position:relative}}
img{{width:100%;display:block;background:#000}}
.ng{{position:absolute;top:8px;left:8px;right:8px;background:rgba(190,120,10,.92);
     font-size:10.5px;padding:3px 7px;border-radius:3px;line-height:1.4}}
figcaption{{padding:8px 10px;font-size:11.5px;line-height:1.6}}
.d{{color:#9cb}} .tag{{color:#777;font-size:10.5px}}
</style>
<h1>{html.escape(args.brand)} 素材カタログ <span class=n>{len(out)}本</span></h1>
{''.join(secs)}"""
    hp = os.path.join(d, "catalog.html")
    with open(hp, "w") as f:
        f.write(page)

    print(json.dumps({"catalog": cp, "html": hp, "counts": catalog["counts"]},
                     ensure_ascii=False))
    if args.open:
        subprocess.run(["open", hp])


if __name__ == "__main__":
    main()
