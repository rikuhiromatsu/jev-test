"""LAMP のお問い合わせフォームに届く案件相談を、確度・優先度で仕分けるCLI。

  uv run triage data/demo_inquiries.csv
  uv run triage data/demo_inquiries.csv --out out/results.csv
  uv run triage --text "問い合わせ本文をそのまま貼る"
  uv run triage --show-questions        # APIを呼ばず、送る質問だけ確認する
"""

import argparse
import asyncio
import csv
import json
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import form
from .inquiries import Inquiry, load_csv
from . import rules
from .questions import DIMENSIONS, FLAG_QUESTIONS, OUR_BUSINESS
from .runner import build_questions, evaluate_all
from .scoring import (
    BUDGET_WEIGHT,
    CONFIDENCE_FLOOR,
    DEADLINE_WEIGHT,
    FLAG_THRESHOLD,
    OUT_OF_SCOPE_FIT,
    RANK_ACTIONS,
    RANK_THRESHOLDS,
    SALES_PITCH_THRESHOLD,
    TriageResult,
)

console = Console()

RANK_STYLE = {"A": "bold red", "B": "yellow", "C": "dim", "除外": "dim strike"}

# 内訳を1列に詰めるための短縮名
_SHORT_LABELS = {
    "fit": "適合",
    "requirement_clarity": "要件",
    "decision_readiness": "検討",
}


def _print_table(results: list[TriageResult]) -> None:
    table = Table(title="案件相談 仕分け結果（確度・優先度）", show_lines=True)
    table.add_column("ID", no_wrap=True)
    table.add_column("会社 / 依頼種別", max_width=20)
    table.add_column("優先", justify="center", no_wrap=True)
    table.add_column("スコア", justify="right", no_wrap=True)
    table.add_column("内訳", no_wrap=True)
    table.add_column("次アクション / 備考", max_width=26)

    for r in sorted(results, key=lambda r: (r.rank == "除外", -r.composite)):
        breakdown = " ".join(
            f"{_SHORT_LABELS[d.dimension.key]}{d.raw_score:.1f}"
            f"{'?' if d.confidence < CONFIDENCE_FLOOR else ''}"
            for d in r.dimensions
        )
        breakdown += f"\n[dim]予算{r.budget_score:.2f} 納期{r.deadline_score:.2f}[/]"

        action = r.action
        if r.needs_human_review:
            action = f"[magenta]要確認[/] {action}"
        if r.notes:
            action += f"\n[dim]{' / '.join(r.notes)}[/]"

        table.add_row(
            r.inquiry_id,
            f"{r.company}\n[dim]{r.project_type}[/]",
            f"[{RANK_STYLE[r.rank]}]{r.rank}[/]",
            f"{r.composite:.2f}",
            breakdown,
            action,
        )

    console.print(table)
    console.print(
        f"[dim]内訳の上段は自由記述からのJev判定（水準番号、0が最低）。"
        f"? は confidence < {CONFIDENCE_FLOOR}。下段の予算・納期は選択値からコードで算出した0〜1。[/]"
    )

    flagged = [r for r in results if r.needs_human_review]
    if flagged:
        console.print(f"\n[magenta]人が確認すべき件: {len(flagged)}件[/]")
        for r in flagged:
            reason = "、".join(r.low_confidence_labels) or "売り込みか判断つかず"
            console.print(f"  - {r.inquiry_id} {r.company}: 判断が割れた軸 = {reason}")


def _print_detail(result: TriageResult) -> None:
    console.print(
        f"[bold]優先度 {result.rank}[/]  複合スコア {result.composite:.2f}  → {result.action}"
    )
    if result.needs_human_review:
        console.print("[magenta]confidence が低い軸があるため、人が確認すること[/]")
    for d in result.dimensions:
        console.print(
            f"  {d.dimension.label}: {d.raw_score:.1f}/{len(d.dimension.levels) - 1}"
            f"  (重み {d.dimension.weight:.2f}, confidence {d.confidence:.2f})"
        )
        console.print(f"    [dim]{d.level_label}[/]")
    if result.has_budget:
        console.print(
            f"  予算: {result.budget_score:.2f} (重み {BUDGET_WEIGHT:.2f}) "
            f"ルール算出 ← {result.budget}"
        )
    else:
        console.print("  [dim]予算: 未入力のため重みから除外[/]")
    if result.has_deadline:
        console.print(
            f"  納期: {result.deadline_score:.2f} (重み {DEADLINE_WEIGHT:.2f}) "
            f"ルール算出 ← {result.deadline}"
        )
    else:
        console.print("  [dim]納期: 未入力のため重みから除外[/]")
    for key, (label, _) in FLAG_QUESTIONS.items():
        console.print(f"  [dim]{label}: {result.nouls.get(key, 0.0):.2f}[/]")
    if result.notes:
        console.print(f"  備考: {' / '.join(result.notes)}")


def _write_csv(results: list[TriageResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ["id", "company", "project_type", "rank", "composite", "needs_human_review"]
    for dim in DIMENSIONS:
        header += [f"{dim.key}_score", f"{dim.key}_confidence"]
    header += ["budget_score", "deadline_score"]
    header += list(FLAG_QUESTIONS)
    header += ["notes"]

    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for r in sorted(results, key=lambda r: (r.rank == "除外", -r.composite)):
            row = [
                r.inquiry_id,
                r.company,
                r.project_type,
                r.rank,
                f"{r.composite:.3f}",
                "1" if r.needs_human_review else "0",
            ]
            for d in r.dimensions:
                row += [f"{d.raw_score:.2f}", f"{d.confidence:.2f}"]
            row += [f"{r.budget_score:.2f}", f"{r.deadline_score:.2f}"]
            row += [f"{r.nouls.get(k, 0.0):.2f}" for k in FLAG_QUESTIONS]
            row.append(" / ".join(r.notes))
            writer.writerow(row)
    console.print(f"[green]書き出しました:[/] {path}")


def _write_json(inquiries, results: list[TriageResult], path: Path) -> None:
    """入力と判定結果をまとめて書き出す。デモ画面などの外部利用向け。"""
    by_id = {i.id: i for i in inquiries}
    payload = {
        # 判定基準そのもの。画面の「仕分けの型」はこれを描画するので、
        # コード側を変えれば書き出し直すだけで表示も追従する。
        "our_business": OUR_BUSINESS.strip(),
        "dimensions": [
            {
                "key": d.key,
                "label": d.label,
                "weight": d.weight,
                "levels": d.levels,
                "instructions": d.instructions,
            }
            for d in DIMENSIONS
        ],
        "rule_weights": {"budget": BUDGET_WEIGHT, "deadline": DEADLINE_WEIGHT},
        "rule_tables": {
            "budget": rules.BUDGET_SCORES,
            "deadline": rules.DEADLINE_SCORES,
        },
        "flags": {
            k: {"label": label, "instructions": instructions}
            for k, (label, instructions) in FLAG_QUESTIONS.items()
        },
        "gates": {
            "budget_floor_option": rules.BUDGET_FLOOR_OPTION,
            "out_of_scope_fit": OUT_OF_SCOPE_FIT,
            "sales_pitch_threshold": SALES_PITCH_THRESHOLD,
            "flag_threshold": FLAG_THRESHOLD,
        },
        "confidence_floor": CONFIDENCE_FLOOR,
        "rank_thresholds": [{"min": t, "rank": r} for t, r in RANK_THRESHOLDS],
        "rank_actions": RANK_ACTIONS,
        "results": [],
    }
    for r in sorted(results, key=lambda r: (r.rank == "除外", -r.composite)):
        inq = by_id[r.inquiry_id]
        payload["results"].append(
            {
                "id": r.inquiry_id,
                "received_at": inq.received_at,
                "company": r.company,
                "name": inq.name,
                "email": inq.email,
                "referral": inq.referral,
                "renewal_url": inq.renewal_url,
                "project_type": r.project_type,
                "project_status": inq.project_status,
                "challenges": inq.challenges,
                "challenge_note": inq.challenge_note,
                "message": inq.message,
                "free_text": inq.free_text,
                "pages": r.pages,
                "budget": r.budget,
                "deadline": r.deadline,
                "rank": r.rank,
                "composite": round(r.composite, 4),
                "action": r.action,
                "notes": r.notes,
                "needs_human_review": r.needs_human_review,
                "budget_score": r.budget_score,
                "deadline_score": r.deadline_score,
                "dimensions": [
                    {
                        "key": d.dimension.key,
                        "score": round(d.raw_score, 3),
                        "confidence": round(d.confidence, 3),
                        "level_label": d.level_label,
                    }
                    for d in r.dimensions
                ],
                "nouls": {k: round(v, 3) for k, v in r.nouls.items()},
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    console.print(f"[green]書き出しました:[/] {path}")


def _show_questions() -> None:
    payload = {}
    for key, q in build_questions().items():
        entry = {"type": type(q).__name__.lower(), "instructions": q.instructions}
        criteria = getattr(q, "criteria", None)
        if criteria:
            entry["criteria"] = criteria
        payload[key] = entry
    console.print_json(json.dumps(payload, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Jevで案件相談の問い合わせを仕分ける")
    parser.add_argument("csv_path", nargs="?", type=Path, help="フォーム送信内容のCSV")
    parser.add_argument("--text", help="本文を直接渡して1件だけ判定する")
    parser.add_argument("--out", type=Path, help="結果を書き出すCSVのパス")
    parser.add_argument("--json", type=Path, help="結果と入力をJSONで書き出すパス")
    parser.add_argument(
        "--budget", default="", help=f"--text と併用。{' / '.join(form.BUDGETS)}"
    )
    parser.add_argument(
        "--deadline", default="", help=f"--text と併用。{' / '.join(form.DEADLINES)}"
    )
    parser.add_argument(
        "--show-questions",
        action="store_true",
        help="APIを呼ばず、Jevに送る質問定義だけを表示する",
    )
    args = parser.parse_args()

    if args.show_questions:
        _show_questions()
        return 0

    if not args.csv_path and not args.text:
        parser.error("CSVのパスか --text のどちらかを指定してください")

    if not os.environ.get("TYPESAFE_API_KEY"):
        console.print(
            "[red]TYPESAFE_API_KEY が未設定です。[/]"
            " https://console.typesafe.ai/keys で発行し、環境変数に設定してください。"
        )
        return 1

    if args.text:
        inquiries = [
            Inquiry(
                id="001",
                company="(直接入力)",
                message=args.text,
                budget=args.budget,
                deadline=args.deadline,
            )
        ]
    else:
        inquiries = load_csv(args.csv_path)

    results = asyncio.run(evaluate_all(inquiries))

    if args.text:
        _print_detail(results[0])
    else:
        _print_table(results)
        thresholds = "、".join(f"{r}≧{t:.2f}" for t, r in RANK_THRESHOLDS if t > 0)
        console.print(f"[dim]ランクのしきい値: {thresholds}（scoring.py で調整）[/]")

    if args.out:
        _write_csv(results, args.out)
    if args.json:
        _write_json(inquiries, results, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
