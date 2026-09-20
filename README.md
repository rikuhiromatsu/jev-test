# 案件相談の仕分け（Jev / TypeSafe System One）

LAMP のお問い合わせフォーム（[/contacts/no-code-web](https://lamp.design/contacts/no-code-web)）に
届く案件相談を、**確度・優先度**で仕分けて A / B / C / 除外 に振り分けるCLI。

## 考え方

判断を Jev に丸投げしない。**確定的に決まることはコードで計算し、自由記述からしか
読み取れないことだけを Jev に聞く**。

| 判断材料 | 担当 | 理由 |
| --- | --- | --- |
| ご予算の上限、ご希望の納期、想定ページ数 | コード（`rules.py`） | 選択式なので一意に決まる。AIに聞く必要がない |
| 相談内容・課題の補足・自由記載の中身 | Jev（`questions.py`） | 意味を読まないと判定できない |
| 重み、しきい値、除外ルール | コード（`scoring.py`） | ポリシーなので人が決める。変えても再推論不要 |

Jev には「優先度を判定して」とは聞かない。System One モデルは
[1問1判断](https://docs.typesafe.ai/primitives.md)が前提なので、
**適合度・要件の具体性・社内の検討進度**という独立した軸に割って聞き、
[composite scoring](https://docs.typesafe.ai/patterns/composite-scoring.md) で合成する。

### スコアの構成（合計 1.00）

| 軸 | 重み | 判定 |
| --- | --- | --- |
| サービス適合度 | 0.25 | Jev（Score 4水準） |
| 予算 | 0.25 | コード（選択値→点数） |
| 要件の具体性 | 0.20 | Jev（Score 4水準） |
| 社内の検討進度 | 0.15 | Jev（Score 4水準） |
| 納期 | 0.15 | コード（選択値→点数） |

### ゲート（スコアより優先される打ち切り）

- **売り込み**（Noul `is_sales_pitch` ≥ 0.70）→ `除外`
- **サービス対象外**（適合度が水準1未満）→ 予算が大きくても `C` 止まり
- **予算下限未満**（「50万円以下」）→ `C` 止まり

### 人に回す条件

Jev の `confidence` が 0.50 未満の軸があれば、自動仕分けせず「要確認」を立てる。
売り込みかどうか判断がつかない（Noul が 0.4〜0.7）ものも同様。
[confidence の使い方](https://docs.typesafe.ai/confidence.md)に沿って、
「分からない」を握りつぶさずに人へ渡す。

## 使い方

```bash
# 1. APIキーを設定（https://console.typesafe.ai/keys で発行）
export TYPESAFE_API_KEY=sk-...

# 2. サンプルで動かす
uv run triage data/demo_inquiries.csv

# 3. 結果をCSVに書き出す
uv run triage data/demo_inquiries.csv --out out/results.csv

# 1件だけ、本文を直接渡して試す
uv run triage --text "採用サイトのリニューアルを検討しています。予算は..."

# APIを呼ばずに、Jevへ送る質問定義だけ確認する
uv run triage --show-questions

# 結果をJSON（判定基準＋全フォーム項目つき）で書き出す
uv run triage data/pool_inquiries.csv --json out/pool_results.json

# 重み・しきい値・ゲートのテスト（APIキー不要）
uv run pytest
```

## 入力CSV

列名は[フォームの項目](https://lamp.design/contacts/no-code-web)に対応する。
`message` 以外はすべて省略可能。`challenges`（解決したい課題）は `/` 区切り。

```
id, received_at, name, company, email, project_type, project_status,
challenges, challenge_note, renewal_url, pages, budget, deadline,
referral, message, free_text
```

`data/demo_inquiries.csv` に、判定の分かれ目になる20件を手で書いてある。
理想的な相談、情報収集段階、売り込み、予算下限未満、対象外（EC・業務システム）など。

## サンプルを生成する

判定基準を変えたときの挙動を見るために、架空の問い合わせを生成できる。

```bash
# 手書き20件のうしろに、生成した80件を足して100件のプールを作る
uv run python -m triage.generate --count 80 --seed 11 \
  --append-to data/demo_inquiries.csv --out data/pool_inquiries.csv
```

`src/triage/generate.py` の `ARCHETYPES` が生成の型。確度の高い相談、情報収集、
曖昧な一言、予算不足、対象外、売り込み、実装のみ、記事制作のみ──の8種類を
`weight` の比率で混ぜる。受信箱の実際の構成に近づけたいときはここを変える。
同じ `--seed` なら同じ結果になる。

生成データはあくまで挙動確認用で、しきい値のチューニングには実際の受信データを使うこと。

## デモ画面

`demo/triage-demo.html` は、100件のプールから20件を引いて仕分けを見せるページ。
判定結果は `out/pool_results.json`（実際に Jev へ通した結果）を埋め込んでいる。
ブラウザからは API キーを扱えないので、画面の［仕分けを実行］は記録済みの判定を再生し、
［サンプルを再生成］はプールから引き直す。ページ上部の「仕分けの型」は
JSON 内の判定基準を描画しているので、`questions.py` / `rules.py` / `scoring.py` を
変えて JSON を書き出し直せば表示も追従する。

```bash
# データを更新してページに埋め込み直す
uv run triage data/pool_inquiries.csv --json out/pool_results.json
python3 - <<'EOF'
import json, pathlib
d = json.load(open("out/pool_results.json", encoding="utf-8"))
data = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
# demo/triage-demo.html の <script id="demo-data"> の中身を差し替える
EOF
```

## チューニングする場所

| 変えたいこと | ファイル |
| --- | --- |
| 自社サービスの説明（適合度の判定精度に直結） | `questions.py` の `OUR_BUSINESS` |
| Jev に聞く軸・質問文・水準・重み | `questions.py` の `DIMENSIONS` |
| 売り込み判定などの yes/no | `questions.py` の `FLAG_QUESTIONS` |
| 予算・納期・ページ数の点数表 | `rules.py` |
| A/B/C のしきい値、ゲート、次アクション文言 | `scoring.py` |
| フォームの選択肢が変わったとき | `form.py`（`rules.py` が整合をassertする） |
| サンプル生成の型・配分 | `generate.py` の `ARCHETYPES` |

しきい値と重みは**自社の実データで調整する前提**の初期値。
実際に受注した相談を通して、A に入るべきものが B に落ちていないかを見ながら動かす。

## 構成

```
src/triage/
  form.py        フォームの選択肢定義（変更があればここ）
  inquiries.py   CSV読み込み と state の組み立て
  questions.py   Jev に聞く質問と重み ← 主なチューニング対象
  rules.py       選択式項目のルール点数化
  runner.py      Jev API 呼び出し（全質問を1リクエストにまとめて並列評価）
  scoring.py     合成・ランク付け・ゲート ← ポリシー
  generate.py    サンプルの問い合わせ生成
  cli.py         表示・CSV／JSON 出力
data/
  demo_inquiries.csv   手で書いた20件
  pool_inquiries.csv   デモ用の100件プール（手書き20＋生成80）
demo/
  triage-demo.html     デモ画面（判定結果を埋め込み済み）
```

## 次にやるなら

- フォームの送信をそのまま流し込む（Webhook / メール / スプレッドシート連携）
- 仕分け結果を Slack に通知し、A は即アサイン
- 実際の受注結果でしきい値を検証し直す（[confidence の閾値は自社データで決める](https://docs.typesafe.ai/confidence.md)）
