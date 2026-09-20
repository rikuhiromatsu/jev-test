"""Jev (TypeSafe System One) に投げる質問の定義。

聞くのは「自由記述からしか読み取れないこと」だけ。予算・納期・ページ数は
選択式なので rules.py がコードで点数化する。
判断軸を足す・文言を変えるときはこのファイルを編集する。
参考: https://docs.typesafe.ai/primitives.md
"""

from dataclasses import dataclass

# 適合度(fit)を判断させるために state に同梱する自社の説明。
# 精度に直結するので、実態と合わなくなったら必ず更新する。
OUR_BUSINESS = """\
Web制作会社。Studio と Framer を使ったノーコードでのサイト制作を専門とし、
戦略設計・情報設計・デザイン・実装・公開後の運用までを一貫して支援する。
対応するサイト種別は、コーポレートサイト、サービスサイト、採用サイト、
オウンドメディア、イベントサイト、LP、および実装のみの受託。
価格帯は50万円以上。デザイン品質と情報設計に強みがあり、
公開後に顧客自身がノーコードで更新・運用できる状態にすることを重視している。
スクラッチ開発、業務システム開発、ECサイトの大規模構築、
人材派遣・常駐要員の提供、広告運用の単体受託は対象外。
"""


@dataclass(frozen=True)
class Dimension:
    """Score 質問ひとつ ＝ 複合スコアの1次元。"""

    key: str
    label: str
    instructions: str
    levels: list[str]
    weight: float

    def normalized(self, score: float) -> float:
        """Jev が返す 0..len-1 の値を 0..1 に正規化する。"""
        return score / (len(self.levels) - 1)


# 自由記述を見て判断する軸。1問1判断に割る（複合判断は System One 向きではない）。
DIMENSIONS: list[Dimension] = [
    Dimension(
        key="fit",
        label="サービス適合度",
        instructions=(
            "`inquiry` の相談内容が、`our_business` に書かれた提供サービスと"
            "どの程度合致しているかを判定する。特に `inquiry.project_type`、"
            "`inquiry.challenges`、`inquiry.message` を見る。"
        ),
        levels=[
            "`our_business` の対象外の依頼（スクラッチ開発、業務システム、大規模EC、常駐要員など）",
            "Web制作ではあるが、`our_business` が重視する領域からは外れている",
            "提供サービスの範囲内で問題なく対応できる依頼",
            "戦略設計や情報設計から関われる、`our_business` の強みに正面から合致した依頼",
        ],
        weight=0.25,
    ),
    Dimension(
        key="requirement_clarity",
        label="要件の具体性",
        instructions=(
            "`inquiry.message`、`inquiry.challenge_note`、`inquiry.free_text` の記述が、"
            "初回提案や概算見積もりを組み立てられる程度に具体的かを判定する。"
            "文章の長さではなく、対象範囲・目的・現状がどれだけ特定できているかで判断する。"
        ),
        levels=[
            "何をしたいのかが読み取れない、または挨拶・接触のみ",
            "やりたいことは分かるが、目的も現状も書かれていない",
            "サイトの目的や現状の課題が具体的に書かれている",
            "対象範囲・目的・現状・参考事例まで揃っていて、そのまま提案に入れる",
        ],
        weight=0.20,
    ),
    Dimension(
        key="decision_readiness",
        label="社内の検討進度",
        instructions=(
            "`inquiry` 全体から、発注に向けた社内の検討がどこまで進んでいるかを判定する。"
            "予算枠の確保、決裁の見通し、社内合意、他社比較の段階といった記述を手がかりにする。"
            "問い合わせ者の熱量ではなく、組織として発注に近いかで判断する。"
        ),
        levels=[
            "情報収集の段階で、社内では何も決まっていない",
            "やりたいという意向はあるが、予算も進め方もこれから",
            "予算枠や時期の目処が立っていて、具体的に会社を探している",
            "発注前提で動いており、決裁の見通しや比較検討の段階まで来ている",
        ],
        weight=0.15,
    ),
]

# 重み付けには使わず、ゲート（自動仕分けの打ち切り）や注意喚起に使う yes/no 判断。
# Noul は確率がそのまま返るので、しきい値は scoring.py で持つ。
FLAG_QUESTIONS: dict[str, tuple[str, str]] = {
    # key: (表示名, instructions)
    "is_sales_pitch": (
        "売り込み",
        "この問い合わせは、制作の相談ではなく `inquiry` の送信者から自社への"
        "営業・売り込み・提携提案である。",
    ),
    "has_deadline_driver": (
        "期日の裏付け",
        "`inquiry` には、納期が動かせない具体的な理由（展示会、キャンペーン、"
        "採用開始、上場、既存サイトの契約終了など）が書かれている。",
    ),
    "wants_ongoing_operation": (
        "運用継続の意向",
        "`inquiry` は、公開して終わりではなく、公開後の更新・運用まで"
        "見据えていることを示している。",
    ),
}

assert abs(sum(d.weight for d in DIMENSIONS) - 0.60) < 1e-9, (
    "自由記述側の重みの合計は0.60。残り0.40は rules.py の予算・納期が持つ"
)
