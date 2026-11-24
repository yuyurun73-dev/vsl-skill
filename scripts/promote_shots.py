#!/usr/bin/env python3
"""切り出したショットのうち採用分を、名前を付けて素材ライブラリに昇格させる。

extract_shots.py の shots.json ＋ 人（Claude）が付けた labels.json から、
採用カットだけを素材フォルダにコピーし、catalog-rules.json に追記する。

使い方:
  python3 promote_shots.py --brand silen --shots <shots.json> --labels <labels.json>

labels.json:
{
 "library": "/Users/u/Desktop/silen material 2/_cuts",
 "labels": [
   {"idx": 12, "category": "mechanism", "name": "気道が潰れる_3D",
    "tags": ["気道","3D"], "desc": "…", "caution": "英語字幕あり"}
 ]
}
- idx は shots.json の通し番号。labels に無い idx は捨てる（＝不採用）
- ファイル名は <category>_<name>_c<idx>.mp4
"""
import argparse, json, os, re, shutil, sys

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--shots", required=True)
    ap.add_argument("--labels", required=True)
    args = ap.parse_args()

    shots = {s["idx"]: s for s in json.load(open(args.shots))}
    lab = json.load(open(args.labels))
    lib = lab["library"]
    os.makedirs(lib, exist_ok=True)

    rules_path = os.path.join(CACHE, args.brand, "catalog-rules.json")
    rules = json.load(open(rules_path))
    existing = {r["match"] for r in rules["rules"]}

    made, missing, added = [], [], 0
    for L in lab["labels"]:
        s = shots.get(L["idx"])
        if not s or not os.path.exists(s["clip"]):
            missing.append(L["idx"])
            continue
        safe = re.sub(r"[^\w一-龥ぁ-んァ-ヶー]", "_", L["name"])[:48]
        fn = f"{L['category']}_{safe}_c{L['idx']:04d}.mp4"
        dst = os.path.join(lib, fn)
        if not os.path.exists(dst):
            shutil.copy2(s["clip"], dst)
        made.append(dst)

        match = "^" + re.escape(fn.replace(".mp4", ""))
        if match not in existing:
            rule = {"match": match, "category": L["category"],
                    "tags": L.get("tags", []),
                    "desc": L.get("desc", "") + f"（{s['src']} の {s['start']}s から）"}
            if L.get("caution"):
                rule["caution"] = L["caution"]
            rules["rules"].insert(0, rule)   # 個別ルールは総称ルールより前に置く
            existing.add(match)
            added += 1

    with open(rules_path, "w") as f:
        json.dump(rules, f, ensure_ascii=False, indent=1)

    print(json.dumps({"library": lib, "copied": len(made), "rules_added": added,
                      "missing_idx": missing}, ensure_ascii=False))


if __name__ == "__main__":
    main()
