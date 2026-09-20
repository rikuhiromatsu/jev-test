"""選択式の項目を、コード側のルールだけで点数化する。

予算・納期・ページ数は選択肢が決まっているので、AIに聞く必要がない。
System One に渡すのは自由記述からしか読み取れない判断だけにする。
参考: https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md
"""

from . import form

# 予算上限の選択値 → 0..1。LAMP の下限は50万円なので「50万円以下」は0。
BUDGET_SCORES: dict[str, float] = {
    "50万円以下": 0.00,
    "50万円": 0.30,
    "100万円": 0.50,
    "200万円": 0.70,
    "300万円": 0.85,
    "400万円": 0.95,
    "500万円以上": 1.00,
}

# 納期 → 0..1。短すぎる納期は品質リスクなので満点にしない。
# 未定は「検討が進んでいない」シグナルとして低く置く。
DEADLINE_SCORES: dict[str, float] = {
    "1ヶ月以内": 0.60,
    "2ヶ月以内": 0.90,
    "3ヶ月以内": 1.00,
    "4ヶ月以内": 0.90,
    "半年以内": 0.70,
    "1年以内": 0.40,
    "1年以上": 0.20,
    "現時点では未定": 0.15,
}

# 規模感。単体では重みを持たせず、予算との整合チェックに使う。
PAGE_SCALE: dict[str, int] = {
    "5ページ以下": 1,
    "6-10ページ": 2,
    "11-20ページ": 3,
    "21ページ以上": 4,
}

# 予算下限。これ以下は受けられないので、確度判定以前に落とす。
BUDGET_FLOOR_OPTION = "50万円以下"

# 規模に対して最低限ほしい予算（ページ数スケール → 予算スコアの下限）。
# 下回ると「予算と規模が釣り合っていない」フラグを立てる。
SCALE_BUDGET_EXPECTATION: dict[int, float] = {1: 0.0, 2: 0.30, 3: 0.50, 4: 0.70}


def budget_score(budget: str) -> float:
    return BUDGET_SCORES.get(budget.strip(), 0.0)


def deadline_score(deadline: str) -> float:
    return DEADLINE_SCORES.get(deadline.strip(), 0.15)


def below_budget_floor(budget: str) -> bool:
    return budget.strip() == BUDGET_FLOOR_OPTION


def budget_scale_mismatch(budget: str, pages: str) -> bool:
    """規模の割に予算が低い組み合わせを検出する。"""
    scale = PAGE_SCALE.get(pages.strip())
    if scale is None:
        return False
    return budget_score(budget) < SCALE_BUDGET_EXPECTATION[scale]


# フォームの選択肢が変わったのに点数表を直し忘れる事故を防ぐ。
assert set(BUDGET_SCORES) == set(form.BUDGETS), "予算の選択肢と点数表がずれている"
assert set(DEADLINE_SCORES) == set(form.DEADLINES), "納期の選択肢と点数表がずれている"
assert set(PAGE_SCALE) == set(form.PAGE_COUNTS), "ページ数の選択肢と点数表がずれている"
