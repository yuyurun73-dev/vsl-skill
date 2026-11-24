---
name: vsl
description: VSLを台本から完パケmp4まで一気通貫で作る。台本承認だけ人間、素材生成・ナレ・テロップ焼き込み・結合・QC・納品は自動。「VSL作って」「VSL量産」「新しいアングルのVSL」「/vsl <brand> <アングル>」で使う。
---

# VSL自動制作

台本を書いて終わり、ではなく**完パケmp4まで出す**。

**現在の対象はSILENのみ。**negiraiは`brands/negirai.json`に置いてあるが運用外。

## 2つのルート

| | Aルート（アバターあり） | Bルート（Bロールのみ） |
|---|---|---|
| 喋り手 | **本人がHeyGenで作って渡してくる** | 無し |
| 尺のマスター | 渡されたHeyGen動画の音声 | 行ごとに生成したナレ音声 |
| Bロール | 喋りの上に**差し込む**（音声は触らない） | シーンとして並べる |
| 組み立て | `assemble_cutaway.py` | `assemble.py` |
| 事前工程 | `align.py`（音声↔台本の位置合わせ） | 不要（行ごとに尺が分かる） |

どちらでもBロールの出どころは同じ：**まず在庫カタログ、足りなければHiggsfieldで生成**。

## 絶対ルール

1. **台本は必ずVSLコースのwikiから作る。** 記憶や勘で書かない。手順は下の「① 台本」の通り。
2. **素材は在庫を先に見る。** カタログに無い絵だけ生成する。
3. **`caution` が付いた素材は、その注意を潰してから使う。**（焼き込み英語テロップ・透かし・他社ブランド・特定できる話者）。潰し方＝その区間を使わない／クロップで切る／自分のテロップ帯で隠す。
4. **台本承認までは生成を回さない。** 承認後は最後まで走り切って結果だけ報告する。
5. **ブランド規約は `brands/silen.json` の `copy_rules` を全部適用する。**
6. 薬機法・景表法の指摘や但し書きは足さない。本人の領域。

## 走らせ方

```
/vsl silen 酸素低下アングル                    # 台本まで出して止まる
/vsl silen 酸素低下 --resume <proj>            # 途中から
```

プロジェクトは `~/Downloads/vsl/silen-<slug>-<YYYYMMDD>/`。
**shotlist.json が唯一の正本。** 直したら `build_plan.py` を打ち直す。

---

## ① 台本 — VSLコースのwikiから作る

生成を1つも回す前に、この順で必ず読む（`~/llm-wiki/wiki/paid-traffic/vsl-creative/`）:

| 順 | ページ | 何を取りに行くか |
|---|---|---|
| 0 | `rmbc2-course-hub.md` | 入口。ここから今回使う型を選ぶ |
| 1 | `funnel-selection-matrix-15-factors.md` | 15項目を採点 → **尺と段数が決まる**。VSL前に必ず通す |
| 2 | `infeed-vs-onpage-vsl.md` | イン・フィードかオンページかで構造が違う。取り違えない |
| 3 | `classic-vsl-structure.md`（長尺）/ `mini-vsl-structures.md`（短尺） | 骨格 |
| 4 | `vsl-8-components-framework.md` | 8構成要素の充足チェック |
| 5 | `vsl-retention-engineering.md` | 離脱ポイントの潰し方 |
| 6 | `swipe-nooro-infeed-medium-vsl.md` | 実物スワイプ |

足りなければ原典 `~/llm-wiki/raw/vsl-course/` と `~/llm-wiki/raw/rmbc2-full/` を直接読む。
ブランドの既存台本（`wiki/brands/<brand>/*-vsl-script-*.md`）も読んで、勝ち型から外れていないか照合する。

書くときの型:
- `brands/<brand>.json` の `winning_format` に従う。実績で裏が取れている型から動かさない。
- フックは3案出して1案を採用（残りは量産用に残す）。
- CTAには**希少性（在庫不足・残りわずか）を必ず入れる**。価格は入れない。
- 読点は列挙・言い換え・引用の区切りだけ。接続助詞の後の「、」は全部削る（ElevenLabs対策）。
- 誤読する漢字はひらがなに開く（方→ひと、諦→あきらめ、煮沸→お湯で煮る）。

**ここで止めて台本を見せる。** 承認が出るまで次に進まない。

---

## ② HeyGen待ち（Aルートのみ）

台本が通ったら**本人がHeyGenでアバター動画を作る**。出来たら `<proj>/base/heygen.mp4` に置いてもらう。
待っている間に②'（ショットリスト）を進めておく。

置かれたら位置合わせ:
```bash
python3 ~/.claude/skills/vsl/scripts/align.py <proj>/base/heygen.mp4 <proj>/shotlist.json
# → timeline.json（各行の開始/終了秒）
```
whisper.cppで文字起こし→**台本の文字列と突き合わせる**ので、聞き取りの誤字は捨てられる（正は台本側）。
`low_confidence` に出た行は拾えていない。台本とアバターの読み上げがズレている可能性があるので中身を見る。

Bルート（アバターなし）はこの工程を飛ばす。

---

## ②' ショットリスト

台本を `shotlist.json` に割る。**1行 = 1テロップ帯**。1行は息継ぎ1つ分、長くても30字前後。

各シーンの `source`:

| type | 意味 |
|---|---|
| `base` | アバターを映したまま（Aルートのみ・既定） |
| `stock` | **在庫から引く。まずこれを探す** |
| `generate` | 在庫に無い絵だけHiggsfieldで作る |

Aルートでは `stock`/`generate` のシーンが「その行を喋っている区間に被さるBロール」になる。
`lead` / `tail` で差し込みの前後を伸ばせる（既定は後ろ0.25秒）。

**在庫の引き方（毎回ここから）**:
```bash
# カタログを読む。カテゴリー・タグ・caution が付いている
cat ~/.claude/skills/vsl/cache/silen/catalog.json
python3 ~/.claude/skills/vsl/scripts/categorize.py --brand silen --open   # 目で見たい時
```
台本の段とカテゴリーの対応（既定の当て方）:

| 台本の段 | 引くカテゴリー |
|---|---|
| フック | `hook`（ナレ入り完成版はテロップ焼き込み済み。二重に載せない） |
| 問題提起 | `symptom_night` → `wife` → `symptom_day` |
| なぜ全部効かないか | `failed_fix`（鼻テープ→口テープ→CPAP→市販マウスピース→横向き枕→禁酒） |
| メカニズム | `mechanism` ＋ `demo`（ストロー/ホースで腹落ちさせる） |
| **放置するとどうなるか** | `danger_body`（酸素低下→脳→心臓）。SILENの危険アングルの核 |
| 原因は下あご | `anatomy_jaw` |
| 既存ルートの手間 | `clinic`（歯科の型取り・検査・費用） |
| ベネフィット | `after` |
| CTA | `product` |

自社素材で足りなければ `stock_anatomy` / `stock_sleep` / `stock_misc` を混ぜる。
`swipe_competitor` は**未切り出しの他社VSL原本**。使えるカットは既に切り出して上のカテゴリーに入っているので、
ここを直接使うのは「まだ拾っていない絵が要る」時だけ（その時は `extract_shots.py` → `promote_shots.py`）。

**外部素材の使い分け（自社が足りない時だけ）**
- `stock_anatomy` … ブランド性が薄い。ほぼそのまま差し込める
- `stock_sleep` … 顔が外国人。**日本人の絵の直後に顔アップを置かない**。寄り／暗所／手元の区間を選ぶ
- `stock_misc` … 比喩・生活シーンの転用
- `swipe_competitor` … 画だけ抜く。ブランド名・英語字幕・話者の顔が映る区間は避ける

在庫にも外部にも無い絵だけ `generate` にする。

素材が増えたら:
```bash
python3 ~/.claude/skills/vsl/scripts/index_broll.py "/Users/u/Desktop/silen material 2" --brand silen
# 新顔は unsorted に落ちる → contact_sheet.py で見て catalog-rules.json に1行足す
python3 ~/.claude/skills/vsl/scripts/contact_sheet.py --index ~/.claude/skills/vsl/cache/silen/broll-index.json
python3 ~/.claude/skills/vsl/scripts/categorize.py --brand silen
```

割り終えたら:
```bash
python3 ~/.claude/skills/vsl/scripts/build_plan.py <proj>/shotlist.json
```
- shotlist に `"base"` があれば → `manifest_cutaway.json`（Aルート）
- 無ければ → `manifest.json` ＋ `todo.vo`（Bルート）
- どちらも `todo.json` に「まだ無い素材」が出る。空になるまで③を回す

---

## ③ 素材生成（Higgsfield MCP）

まず `get_workflow_instructions` をノー引数で叩き、該当ワークフローがあればそれに従う。

**ナレーション（Bルートの todo.vo だけ）**
- Aルートでは作らない。喋りはHeyGen動画の中に入っている
- `brands/silen.json` の `voice` をそのまま使う（`voice_id`）
- **1行ずつ生成する。**長文を一括で投げると話速が縮んで語が潰れる
- `generate_audio_batch` + `jobs_wait` → `show_generation_by_ids` でURL → `curl` で `vo/<id>.mp3` に落とす
- 濁点落ち・誤読は再生成では直らない。**語を替える**（例: 煮沸→お湯で煮る）

**B-roll生成（todo.clips の type=generate）**
- `image_references` にペルソナ基準画像を渡して人物を固定
- プロンプトに `no music, no on-screen text` を明記。環境音は指定する
- preset推薦が返ったら `declined_preset_id` 付きで即再送
- 台本のセリフは平文で書く。Unicodeエスケープで書くと打ち間違いに気づけない

**MCPが落ちたら**: job_idを `state.json` に書いてから待つ。落ちたら新規セッションで `show_generation_by_ids` から回収して再開する（同一セッションで粘らない）。

---

## ④ テロップ

```bash
python3 ~/.claude/skills/vsl/scripts/render_telop.py <proj>/telopspec.json
```
確定仕様（変更禁止）: 黒帯60% / 太明朝W6 白＋黒縁 / 1帯1フレーズ / 恐怖=`<r>`赤 / オファー=`<y>`黄。
冒頭の帯は赤を効かせる。折り返しと文字サイズは自動。

テロップ文は「一読で画が浮かぶ」こと。圧縮して短くするより、具体で少し長い方を採る。

---

## ⑤ 組み立て

**Aルート（HeyGenアバター）**
```bash
python3 ~/.claude/skills/vsl/scripts/assemble_cutaway.py <proj>/manifest_cutaway.json
```
アバターの音声には触らない。Bロールは指定区間だけ映像を被せる。素材が短ければ自動でループ。

**Bルート（Bロールのみ）**
```bash
python3 ~/.claude/skills/vsl/scripts/assemble.py <proj>/manifest.json
python3 ~/.claude/skills/vsl/scripts/assemble.py <proj>/manifest.json --only S07   # 直しは1シーンだけ
```
VOが尺のマスター。映像は自動でトリム/ループ。

どちらも9:16にクロップ、最後に-14 LUFSへ正規化。

---

## ⑥ QC（納品前に必ず）

```bash
python3 ~/.claude/skills/vsl/scripts/qc.py <proj>/<name>.mp4 --n 12 --audio
```
出たjpgを**自分でReadして目視する**。見るのは4つ:
1. 化け文字（生成映像に紛れ込む日本語モドキ）
2. 顔ブレ（同一人物のはずのシーンで顔が変わっていないか）
3. テロップの見切れ・帯の位置
4. **scammyに見えないか**（下の判定表。1つでも当たれば直すまで納品しない）

### ⚠ scammy判定（納品前に必ず通す・2026-09-21 本人指示で必須化）

| # | 当たったらNG | 直し方 |
|---|---|---|
| 1 | 証言が実在しない（他社の翻案・創作） | 自社レビュー/実コメントの原文に差し替える。無ければ証言ごと落とす |
| 2 | 数字・期限の出典が出せない | 出典を付けるか「〜と報告されています」で主語を研究側に逃がす。逃がせないなら削る |
| 3 | 権威が匿名／実在の人物を無断で一人称で喋らせている | 架空ペルソナを立てて肩書きだけ名乗る。実在名は引用の形にする |
| 4 | 希少性が実態と違う（在庫・期限） | 実際の在庫運用と文言を一致させる |
| 5 | 断定的な治癒表現（治る・効く・改善する） | 機構の説明に戻す。「材料を届ける」まで |
| 6 | アバターがAIだと分かる（同一ポーズが4秒以上続く） | B-rollを差し込んで割る。**アバターは全体の3割まで** |
| 7 | 動画の保証条件と着地ページの条件が違う | 動画側を実条件に合わせる |
| 8 | Before/Afterの捏造 | 使わない |
| 9 | テロップの煽りが本文より強い | 本文と同じ強度に落とす |

音声側は `long_silences` と `lufs` を機械で確認。長い無音が出たらTTSの生成事故を疑う。

---

## ⑦ 納品

- 完パケを `~/Downloads/` にもコピーする
- 一覧ギャラリーHTMLを作って **`open` で自動的に開く**（添付だけで終わらせない）
- 何を作ったかを `~/llm-wiki/wiki/brands/<brand>/` に記録するのは**指示された時だけ**

報告は「どのアングルで・何分・どの素材を在庫から引いて・何本生成したか・クレジット消費」を数字で出す。

---

## Meta入稿（明示指示があった時だけ）

`ads_creative_upload_video` → `ads_create_creative` → `ads_create_ad` の順。
**必ず一時停止(PAUSED)で作る。**アカウントは `brands/<brand>.json` の `ad_account`。
SILENとnegiraiのアカウントを絶対に混同しない（アカウント名と実ブランドが一致していない）。

## 参照

- 台本の原典: `~/llm-wiki/wiki/paid-traffic/vsl-creative/rmbc2-course-hub.md`
- テロップ仕様: `[[silen-telop-spec]]` / TTS: `[[tts-chunked-generation]]` `[[script-tts-comma-style]]`
- 声: `[[silen-voice-clone]]` / アバター: `wiki/brands/silen/silen-doctor-voice-spec-2026-08-06.md`
