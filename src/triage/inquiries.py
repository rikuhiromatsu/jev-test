"""フォーム送信内容の読み込みと、Jev に渡す state の組み立て。

CSV の列名は LAMP のお問い合わせフォーム（/contacts/no-code-web）の項目に対応する。
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .questions import OUR_BUSINESS

# CSV の列名 → Inquiry の属性名
COLUMN_MAP = {
    "id": "id",
    "received_at": "received_at",
    "name": "name",
    "company": "company",
    "email": "email",
    "project_type": "project_type",          # 何の依頼を検討していますか？
    "project_status": "project_status",      # 貴社のプロジェクトの現状
    "challenges": "challenges",              # 解決したい課題（最大3つ、"/" 区切り）
    "challenge_note": "challenge_note",      # 課題の補足説明
    "renewal_url": "renewal_url",            # リニューアル対象URL
    "pages": "pages",                        # 想定ページ数
    "budget": "budget",                      # ご予算の上限
    "deadline": "deadline",                  # ご希望の納期
    "referral": "referral",                  # LAMPを知ったきっかけ
    "message": "message",                    # お問い合わせ内容
    "free_text": "free_text",                # 相談内容の自由記載欄
}

CHALLENGE_SEPARATOR = "/"

# 書き出し時の列順（generate.py が使う）
CSV_COLUMNS_ORDER = list(COLUMN_MAP)


@dataclass
class Inquiry:
    id: str = ""
    received_at: str = ""
    name: str = ""
    company: str = ""
    email: str = ""
    project_type: str = ""
    project_status: str = ""
    challenges: list[str] = field(default_factory=list)
    challenge_note: str = ""
    renewal_url: str = ""
    pages: str = ""
    budget: str = ""
    deadline: str = ""
    referral: str = ""
    message: str = ""
    free_text: str = ""

    def to_state(self) -> dict:
        """名前付きJSONで渡す。質問文からは `inquiry.message` のように参照する。

        予算・納期・ページ数も state には入れる（文脈として効くため）が、
        点数化はしない。それは rules.py の仕事。
        参考: https://docs.typesafe.ai/concepts/state.md
        """
        return {
            "inquiry": {
                "company": self.company,
                "project_type": self.project_type,
                "project_status": self.project_status,
                "challenges": self.challenges,
                "challenge_note": self.challenge_note,
                "is_renewal": bool(self.renewal_url),
                "pages": self.pages,
                "budget_ceiling": self.budget,
                "desired_deadline": self.deadline,
                "message": self.message,
                "free_text": self.free_text,
            },
            "our_business": OUR_BUSINESS,
        }

    @property
    def label(self) -> str:
        return self.company or self.name or self.id


def load_csv(path: Path) -> list[Inquiry]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{path} に行がありません")
    if "message" not in rows[0]:
        raise ValueError(f"{path} に必須列 message がありません")

    inquiries = []
    for i, row in enumerate(rows):
        fields = {
            attr: (row.get(col) or "").strip()
            for col, attr in COLUMN_MAP.items()
            if col in row
        }
        fields["id"] = fields.get("id") or f"{i + 1:03d}"
        challenges = fields.pop("challenges", "")
        inquiries.append(
            Inquiry(
                challenges=[
                    c.strip() for c in challenges.split(CHALLENGE_SEPARATOR) if c.strip()
                ],
                **fields,
            )
        )
    return inquiries
