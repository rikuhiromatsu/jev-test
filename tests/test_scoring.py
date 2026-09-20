"""APIを呼ばずに、重み・しきい値・ゲートのロジックだけを検証する。

Jev の答えはダミーに差し替える。モデルの精度ではなく、
「答えをどう合成して仕分けるか」を固定するためのテスト。
"""

from dataclasses import dataclass

import pytest

from triage.inquiries import Inquiry
from triage.questions import DIMENSIONS, FLAG_QUESTIONS
from triage.scoring import CONFIDENCE_FLOOR, build_result


@dataclass
class FakeScore:
    score: float
    confidence: float = 0.9


@dataclass
class FakeNoul:
    noul: float


class FakeResponse:
    def __init__(self, scores: dict, nouls: dict):
        self.scores = scores
        self.nouls = nouls


def response(level: float = 3.0, confidence: float = 0.9, **nouls) -> FakeResponse:
    """全Score軸を同じ水準で埋めたダミーレスポンス。"""
    return FakeResponse(
        scores={d.key: FakeScore(level, confidence) for d in DIMENSIONS},
        nouls={k: FakeNoul(nouls.get(k, 0.0)) for k in FLAG_QUESTIONS},
    )


def inquiry(budget: str = "300万円", deadline: str = "3ヶ月以内", pages: str = "6-10ページ") -> Inquiry:
    return Inquiry(
        id="T-1", company="テスト株式会社", project_type="コーポレートサイト",
        budget=budget, deadline=deadline, pages=pages, message="テスト",
    )


def test_満点は複合スコア1になる():
    r = build_result(inquiry(budget="500万円以上", deadline="3ヶ月以内"), response(level=3.0))
    assert r.composite == pytest.approx(1.0)
    assert r.rank == "A"


def test_最低評価は複合スコア0になる():
    r = build_result(inquiry(budget="50万円以下", deadline="現時点では未定"), response(level=0.0))
    assert r.composite == pytest.approx(0.15 * 0.15)  # 納期「未定」の0.15のみ
    assert r.rank == "C"


def test_売り込みはスコアに関係なく除外される():
    r = build_result(inquiry(), response(level=3.0, is_sales_pitch=0.95))
    assert r.composite > 0.7
    assert r.rank == "除外"


def test_予算下限未満は高評価でもCに落ちる():
    r = build_result(inquiry(budget="50万円以下"), response(level=3.0))
    assert r.rank == "C"
    assert "予算下限未満" in r.notes


def test_confidenceが低い軸があれば人のレビューに回す():
    r = build_result(inquiry(), response(level=2.0, confidence=CONFIDENCE_FLOOR - 0.01))
    assert r.needs_human_review
    assert len(r.low_confidence_labels) == len(DIMENSIONS)


def test_売り込みかどうか判断がつかない場合も人に回す():
    r = build_result(inquiry(), response(level=2.0, is_sales_pitch=0.5))
    assert r.rank != "除外"
    assert r.needs_human_review
    assert "売り込みか判断つかず" in r.notes


def test_規模に対して予算が低い組み合わせを検出する():
    r = build_result(inquiry(budget="50万円", pages="21ページ以上"), response(level=2.0))
    assert "規模に対して予算が低い" in r.notes


def test_Noulフラグが備考に出る():
    r = build_result(
        inquiry(), response(level=2.0, has_deadline_driver=0.9, wants_ongoing_operation=0.8)
    )
    assert "期日に裏付けあり" in r.notes
    assert "運用まで見込み" in r.notes


def test_適合度が低い案件は予算が大きくてもCに落ちる():
    scores = {d.key: FakeScore(3.0) for d in DIMENSIONS}
    scores["fit"] = FakeScore(0.3)  # 対象外の依頼
    r = build_result(
        inquiry(budget="500万円以上", deadline="3ヶ月以内"),
        FakeResponse(scores, {k: FakeNoul(0.0) for k in FLAG_QUESTIONS}),
    )
    assert r.composite > 0.7
    assert r.rank == "C"
    assert "サービス対象外の可能性" in r.notes


def test_予算と納期が未入力なら重みから外して正規化する():
    """本文だけ渡す --text モードで、未入力が最低評価にならないこと。"""
    r = build_result(inquiry(budget="", deadline=""), response(level=3.0))
    assert r.composite == pytest.approx(1.0)
    assert "予算未入力" in r.notes and "納期未入力" in r.notes
    assert not r.below_budget_floor


def test_予算だけ未入力なら納期は効き続ける():
    r = build_result(inquiry(budget="", deadline="1年以上"), response(level=3.0))
    # 自由記述0.60が満点 + 納期0.15*0.20 を 0.75 で正規化
    assert r.composite == pytest.approx((0.60 + 0.15 * 0.20) / 0.75)
