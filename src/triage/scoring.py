"""Jev の答えとルール点を合成して、運用で使える仕分け結果にする。

「どこで線を引くか」はポリシーなのでコード側に置く。ここを変えても
再推論は不要（質問と state が変わっていないため）。
"""

from dataclasses import dataclass, field

from . import rules
from .questions import DIMENSIONS, FLAG_QUESTIONS, Dimension

# 選択式項目の重み。自由記述側（DIMENSIONS）の合計0.60と足して1.00になる。
BUDGET_WEIGHT = 0.25
DEADLINE_WEIGHT = 0.15

# 複合スコア → 優先度ランク。自社の実データを見て調整する。
RANK_THRESHOLDS: list[tuple[float, str]] = [
    (0.70, "A"),
    (0.45, "B"),
    (0.00, "C"),
]

RANK_ACTIONS = {
    "A": "即日フォロー（ヒアリング日程を提示）",
    "B": "通常フォロー（2営業日以内に返信）",
    "C": "テンプレ返信（予算・条件を確認）",
    "除外": "返信不要（営業・対象外）",
}

# Choice/Score の confidence がこれを下回る軸があれば、自動仕分けせず人が見る。
# 参考: https://docs.typesafe.ai/confidence.md
CONFIDENCE_FLOOR = 0.50

# Noul のしきい値。0.5付近は「判断がつかない」であって中間の強さではない。
SALES_PITCH_THRESHOLD = 0.70
FLAG_THRESHOLD = 0.60

# 適合度がこれ未満なら対象外扱い。予算が大きくても優先度は上げない。
# （0..1 に正規化した値。4水準なら 0.34 は「水準1未満」に相当）
OUT_OF_SCOPE_FIT = 0.34


@dataclass
class DimensionResult:
    dimension: Dimension
    raw_score: float      # Jev が返した 0..len-1 の値（水準間の小数もありうる）
    normalized: float     # 0..1
    confidence: float
    level_label: str

    @property
    def weighted(self) -> float:
        return self.normalized * self.dimension.weight


@dataclass
class TriageResult:
    inquiry_id: str
    company: str
    project_type: str
    budget: str
    deadline: str
    pages: str
    dimensions: list[DimensionResult] = field(default_factory=list)
    nouls: dict[str, float] = field(default_factory=dict)

    # --- ルール側の点 ---
    @property
    def has_budget(self) -> bool:
        return bool(self.budget.strip())

    @property
    def has_deadline(self) -> bool:
        return bool(self.deadline.strip())

    @property
    def budget_score(self) -> float:
        return rules.budget_score(self.budget)

    @property
    def deadline_score(self) -> float:
        return rules.deadline_score(self.deadline)

    @property
    def composite(self) -> float:
        """0..1 の複合スコア。自由記述の判断＋選択式のルール点。

        未入力の項目は「最低評価」ではなく重みから外し、残りで正規化する。
        （本文だけ渡す --text モードや、任意項目が空のデータのため）
        """
        total = sum(d.weighted for d in self.dimensions)
        weight = sum(d.dimension.weight for d in self.dimensions)
        if self.has_budget:
            total += self.budget_score * BUDGET_WEIGHT
            weight += BUDGET_WEIGHT
        if self.has_deadline:
            total += self.deadline_score * DEADLINE_WEIGHT
            weight += DEADLINE_WEIGHT
        return total / weight if weight else 0.0

    # --- ゲート（スコア以前に決まること） ---
    @property
    def is_sales_pitch(self) -> bool:
        return self.nouls.get("is_sales_pitch", 0.0) >= SALES_PITCH_THRESHOLD

    @property
    def below_budget_floor(self) -> bool:
        return self.has_budget and rules.below_budget_floor(self.budget)

    @property
    def fit_score(self) -> float:
        """適合度の正規化値（0..1）。"""
        for d in self.dimensions:
            if d.dimension.key == "fit":
                return d.normalized
        return 0.0

    @property
    def out_of_scope(self) -> bool:
        return self.fit_score < OUT_OF_SCOPE_FIT

    @property
    def rank(self) -> str:
        if self.is_sales_pitch:
            return "除外"
        if self.out_of_scope or self.below_budget_floor:
            # 対象外の依頼、または受注できない価格帯。
            # 予算が大きくてもスコアで拾い上げない。
            return "C"
        for threshold, rank in RANK_THRESHOLDS:
            if self.composite >= threshold:
                return rank
        return RANK_THRESHOLDS[-1][1]

    @property
    def action(self) -> str:
        return RANK_ACTIONS[self.rank]

    # --- 人が見るべきかの判定 ---
    @property
    def low_confidence_labels(self) -> list[str]:
        return [
            d.dimension.label for d in self.dimensions if d.confidence < CONFIDENCE_FLOOR
        ]

    @property
    def needs_human_review(self) -> bool:
        return bool(self.low_confidence_labels) or self.is_sales_pitch_uncertain

    @property
    def is_sales_pitch_uncertain(self) -> bool:
        """売り込みかどうか判断がついていない（0.5付近）。"""
        return 0.40 <= self.nouls.get("is_sales_pitch", 0.0) < SALES_PITCH_THRESHOLD

    @property
    def notes(self) -> list[str]:
        """営業が見たときに効く補足。"""
        out = []
        if self.out_of_scope:
            out.append("サービス対象外の可能性")
        if self.below_budget_floor:
            out.append("予算下限未満")
        if not self.has_budget:
            out.append("予算未入力")
        if not self.has_deadline:
            out.append("納期未入力")
        if rules.budget_scale_mismatch(self.budget, self.pages):
            out.append("規模に対して予算が低い")
        if self.nouls.get("has_deadline_driver", 0.0) >= FLAG_THRESHOLD:
            out.append("期日に裏付けあり")
        if self.nouls.get("wants_ongoing_operation", 0.0) >= FLAG_THRESHOLD:
            out.append("運用まで見込み")
        if self.is_sales_pitch_uncertain:
            out.append("売り込みか判断つかず")
        return out


def build_result(inquiry, answers) -> TriageResult:
    """system_one のレスポンスを TriageResult に変換する。

    answers は .scores / .nouls を持つ SystemOneResponse 互換のオブジェクト。
    """
    result = TriageResult(
        inquiry_id=inquiry.id,
        company=inquiry.company,
        project_type=inquiry.project_type,
        budget=inquiry.budget,
        deadline=inquiry.deadline,
        pages=inquiry.pages,
        nouls={key: float(answers.nouls[key].noul) for key in FLAG_QUESTIONS},
    )
    for dim in DIMENSIONS:
        answer = answers.scores[dim.key]
        raw = float(answer.score)
        nearest = max(0, min(int(round(raw)), len(dim.levels) - 1))
        result.dimensions.append(
            DimensionResult(
                dimension=dim,
                raw_score=raw,
                normalized=dim.normalized(raw),
                confidence=float(answer.confidence),
                level_label=dim.levels[nearest],
            )
        )
    return result
