"""Jev (TypeSafe System One) の呼び出し。

1件につき1リクエスト。全質問が同じ state を見るので、Score も Noul も
1回の呼び出しにまとめて投げる（並列評価され、追加の質問はトークン分しか増えない）。
参考: https://docs.typesafe.ai/primitives.md#ask-multiple-questions-together
"""

import asyncio

from typesafe_sdk import AsyncTypeSafeClient, Noul, Score

from .inquiries import Inquiry
from .questions import DIMENSIONS, FLAG_QUESTIONS
from .scoring import TriageResult, build_result

# 同時実行数。レート制限に合わせて調整する。
MAX_CONCURRENCY = 5


def build_questions() -> dict:
    questions: dict = {
        dim.key: Score(instructions=dim.instructions, criteria=list(dim.levels))
        for dim in DIMENSIONS
    }
    for key, (_label, instructions) in FLAG_QUESTIONS.items():
        questions[key] = Noul(instructions=instructions)
    return questions


async def _evaluate_one(
    client: AsyncTypeSafeClient,
    semaphore: asyncio.Semaphore,
    inquiry: Inquiry,
    questions: dict,
) -> TriageResult:
    async with semaphore:
        response = await client.system_one(inquiry.to_state(), questions)
    return build_result(inquiry, response)


async def evaluate_all(inquiries: list[Inquiry]) -> list[TriageResult]:
    """全件を評価して、元の順序のまま返す。"""
    questions = build_questions()
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    async with AsyncTypeSafeClient() as client:
        return await asyncio.gather(
            *(_evaluate_one(client, semaphore, inq, questions) for inq in inquiries)
        )
