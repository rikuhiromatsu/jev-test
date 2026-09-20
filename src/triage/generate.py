"""サンプルの問い合わせを生成する。

デモや、判定基準を変えたときの挙動確認に使う。実データではないので、
しきい値のチューニングには本物の受信データを使うこと。

  uv run python -m triage.generate --count 40 --seed 7 --out data/generated.csv
"""

import argparse
import csv
import random
from pathlib import Path

from .inquiries import CHALLENGE_SEPARATOR, CSV_COLUMNS_ORDER

# 業種ごとの会社名。(会社名, 業種, 事業内容) — 事業内容は文面にそのまま差し込む
COMPANIES = [
    ("東和精機株式会社", "製造", "精密部品の製造"),
    ("カネモト製作所", "製造", "金属加工"),
    ("株式会社ミナミ化成", "製造", "樹脂成形"),
    ("大栄産業株式会社", "製造", "産業機械の設計製造"),
    ("株式会社ルーメン", "SaaS", "業務効率化のSaaS"),
    ("スタックベース株式会社", "SaaS", "開発者向けツールの提供"),
    ("株式会社ハコブネ", "SaaS", "物流管理サービスの提供"),
    ("クラフトワークス株式会社", "SaaS", "受発注プラットフォームの運営"),
    ("医療法人そよ風会", "医療", "内科クリニックの運営"),
    ("まほろば訪問看護ステーション", "医療", "訪問看護"),
    ("株式会社ケアリンク", "介護", "介護施設の運営"),
    ("株式会社志学ゼミナール", "教育", "学習塾の運営"),
    ("ことばの森こども園", "教育", "認定こども園の運営"),
    ("株式会社まなびや", "教育", "オンライン講座の提供"),
    ("株式会社一汁三菜", "飲食", "飲食店チェーンの運営"),
    ("ベーカリーくるみ株式会社", "飲食", "パンの製造小売"),
    ("佐竹建設株式会社", "建設", "総合建設業"),
    ("株式会社ヒカリ電設", "建設", "電気設備工事"),
    ("アーバンリンク株式会社", "不動産", "賃貸仲介"),
    ("株式会社リノベ空間", "不動産", "住宅リノベーション"),
    ("中西会計事務所", "士業", "税務・会計顧問"),
    ("さくら法律事務所", "士業", "企業法務"),
    ("株式会社みなも商店", "小売", "生活雑貨の企画販売"),
    ("キタノ物産株式会社", "小売", "食品の卸売"),
    ("株式会社キャリアブリッジ", "人材", "人材紹介"),
    ("株式会社ワークシフト", "人材", "採用支援"),
    ("一般財団法人地域みらい", "団体", "地域振興事業"),
    ("NPO法人そらのした", "団体", "子育て支援"),
    ("株式会社アオイ印刷", "印刷", "商業印刷"),
    ("株式会社フクロウ研究所", "研究", "受託分析"),
    ("株式会社トウカイ運輸", "物流", "運送・倉庫"),
    ("合同会社ソラミ", "デザイン", "プロダクトの企画開発"),
    ("株式会社ミドリ農園", "農業", "農産物の生産直販"),
    ("株式会社オリオン観光", "観光", "旅行商品の企画"),
    ("株式会社スポルト", "スポーツ", "フィットネスクラブの運営"),
    ("株式会社ヤマト工芸", "製造", "木工製品の製造"),
]

# 予算が取れない層。個人・小規模事業者
SOLO_SENDERS = [
    ("個人", "イラストレーター"),
    ("ネイルサロン ひなた", "サロン"),
    ("まつもと行政書士事務所", "行政書士事務所"),
    ("焙煎所 コトリ", "自家焙煎コーヒー店"),
    ("アトリエ結", "ハンドメイド作家"),
    ("整体院あおぞら", "整体院"),
    ("個人", "フリーランスのカメラマン"),
    ("学習塾みらい", "個人塾"),
]

ROLES_DECIDER = ["代表取締役", "取締役", "執行役員", "事業部長"]
ROLES_MID = ["経営企画室", "広報部 課長", "マーケティング部 マネージャー", "人事部 採用担当"]
ROLES_STAFF = ["総務課", "広報担当", "営業事務", "管理部"]

FIRST = ["健一", "美咲", "亮", "さくら", "直樹", "optional", "翔", "恵", "拓也", "里奈", "純", "千春", "大輔", "優"]
LAST = ["佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村", "小林", "加藤", "吉田", "山田"]


def _name(rng):
    return rng.choice(LAST) + " " + rng.choice([f for f in FIRST if f != "optional"])


# アーキタイプごとの生成規則。
# weight は出現比率。実際の受信箱の構成に近づけたいときはここを変える。
ARCHETYPES = [
    {
        "key": "strong_lead",
        "weight": 3,
        "types": ["コーポレートサイト", "サービスサイト", "採用サイト", "オウンドメディア"],
        "budgets": ["200万円", "300万円", "400万円", "500万円以上"],
        "deadlines": ["2ヶ月以内", "3ヶ月以内", "4ヶ月以内"],
        "pages": ["6-10ページ", "11-20ページ", "21ページ以上"],
        "status": "作りたいサイトの構成などはある程度決まっていて、デザインにこだわりたい",
        "roles": ROLES_DECIDER + ROLES_MID,
        "challenges": [
            "会社のブランドを一新したい",
            "サイトコンテンツやビジュアルの戦略を一緒に整理したい",
            "見せたい情報を最適な形に整理して掲載したい",
            "自社でサイト更新・運用をできるようにしたい",
        ],
        "messages": [
            "{type}のリニューアルをお願いしたいです。{company_kind}を営んでおり、"
            "現在のサイトが{pain}という状態です。{goal}を目的に、情報設計の段階から"
            "一緒に考えていただける会社を探しています。予算は社内で承認済みで、"
            "私が決裁を担当します。{compare}",
            "{type}の新規制作についてご相談です。{company_kind}を手がけており、"
            "{event}に向けて動いています。現状は{pain}ことが課題です。要件はこちらで整理済みですので、"
            "デザインと実装をお任せできる体制を探しています。着手時期と概算をお伺いしたいです。",
            "{type}の制作をご検討いただけますでしょうか。{event}にあたり、"
            "{pain}状況を解消する必要があります。社内の合意は取れており、"
            "今期の予算として確保しています。{compare}",
        ],
        "free": [
            "公開後は自社で更新できる状態にしたいので、Studioを希望しています。",
            "Framerでの制作事例を拝見してご連絡しました。",
            "参考にしたいサイトをいくつかまとめた資料があります。",
            "",
        ],
    },
    {
        "key": "warm",
        "weight": 3,
        "types": ["コーポレートサイト", "サービスサイト", "採用サイト", "LP", "イベントサイト"],
        "budgets": ["100万円", "200万円"],
        "deadlines": ["2ヶ月以内", "3ヶ月以内", "半年以内"],
        "pages": ["5ページ以下", "6-10ページ", "11-20ページ"],
        "status": "とりあえず早くサイトを作ってリリースしたい",
        "roles": ROLES_MID + ROLES_STAFF,
        "challenges": [
            "お問い合わせを増やしたい",
            "顧客からの印象を良くしたい",
            "コンテンツやデザイン、コピーの質を改善したい",
            "見せたい情報を最適な形に整理して掲載したい",
        ],
        "messages": [
            "{type}の制作を検討しています。{company_kind}を行っており、{pain}ため、"
            "{goal}を目指したいと考えています。まずは進め方と概算費用を教えていただけますか。",
            "{type}を作り直したいです。{pain}状態で、{goal}につなげたいと考えています。"
            "予算はこれから社内で詰めるところですが、おおよその目安が分かれば動きやすいです。",
            "{type}についてご相談させてください。{goal}が目的です。{pain}のが悩みで、"
            "どこから手を付けるべきかも含めて相談できればと思っています。",
        ],
        "free": ["", "", "まずはオンラインでお話を伺えればと思います。"],
    },
    {
        "key": "info_gathering",
        "weight": 2,
        "types": ["コーポレートサイト", "採用サイト", "オウンドメディア", "サービスサイト"],
        "budgets": ["100万円", "200万円", "500万円以上"],
        "deadlines": ["1年以内", "1年以上", "現時点では未定"],
        "pages": ["6-10ページ", "11-20ページ"],
        "status": "とりあえず早くサイトを作ってリリースしたい",
        "roles": ROLES_STAFF + ROLES_MID,
        "challenges": [
            "サイト制作をしたいが、何から始めたらいいか分からない",
            "会社のブランドを一新したい",
            "顧客からの印象を良くしたい",
        ],
        "messages": [
            "中期の計画として{type}の刷新を検討事項に挙げています。"
            "まだ時期も担当部署も決まっていませんが、一般的な進め方や相場感を"
            "伺えればと思いご連絡しました。",
            "{type}の制作について情報収集をしています。{company_kind}ですが、"
            "社内でこれから提案していく段階です。他社さんの事例や、"
            "どのくらいの期間・費用がかかるものなのかを知りたいです。",
            "将来的に{type}を作りたいと考えています。まだ具体的には何も決まっておらず、"
            "まずはどんな選択肢があるのかを教えていただきたいです。",
        ],
        "free": ["", "", "社内提案用の資料があれば助かります。"],
    },
    {
        "key": "vague",
        "weight": 2,
        "types": ["コーポレートサイト", "LP"],
        "budgets": ["50万円以下", "50万円"],
        "deadlines": ["現時点では未定", "1ヶ月以内"],
        "pages": ["5ページ以下"],
        "status": "とりあえず早くサイトを作ってリリースしたい",
        "roles": ROLES_STAFF,
        "challenges": ["サイト制作をしたいが、何から始めたらいいか分からない"],
        "messages": [
            "ホームページを作りたいです。よろしくお願いします。",
            "サイトの件で相談したいです。お返事お待ちしております。",
            "見積もりをお願いできますか。詳細は追ってご連絡します。",
            "{type}を作りたいです。費用を教えてください。",
        ],
        "free": ["", "", ""],
    },
    {
        "key": "low_budget",
        "weight": 2,
        "types": ["コーポレートサイト", "LP", "イベントサイト"],
        "budgets": ["50万円以下"],
        "deadlines": ["1ヶ月以内", "2ヶ月以内", "現時点では未定"],
        "pages": ["5ページ以下"],
        "status": "とりあえず早くサイトを作ってリリースしたい",
        "roles": ROLES_STAFF + ["代表"],
        "challenges": ["顧客からの印象を良くしたい", "お問い合わせを増やしたい"],
        "messages": [
            "{company_kind}をしています。{type}を作りたいのですが、"
            "予算があまりありません。安く作る方法があれば教えていただきたいです。",
            "小規模な{type}をお願いしたいです。{pain}ので作り直したいのですが、"
            "予算は多く取れません。ご対応いただける範囲を教えてください。",
            "{type}を最低限の構成で作りたいです。ページ数は少なくて構いません。"
            "予算内に収まるかどうかだけ先に知りたいです。",
        ],
        "free": ["", "", ""],
    },
    {
        "key": "out_of_scope",
        "weight": 2,
        "types": ["上記以外"],
        "budgets": ["200万円", "300万円", "500万円以上"],
        "deadlines": ["3ヶ月以内", "半年以内"],
        "pages": ["21ページ以上", "11-20ページ"],
        "status": "とりあえず早くサイトを作ってリリースしたい",
        "roles": ROLES_MID + ["情報システム部"],
        "challenges": ["その他"],
        "messages": [
            "社内で使う業務システムを作りたいと考えています。"
            "{company_kind}の現場で使う管理画面と、ログイン機能、データベースが必要です。"
            "Webに詳しい会社を探していて問い合わせました。",
            "自社ECサイトのリニューアルを検討しています。商品点数が多く、"
            "基幹システムとの在庫連携と会員別価格の表示を実装したいです。"
            "スクラッチでの開発も視野に入れています。",
            "スマートフォンアプリの開発をお願いできますか。{company_kind}に関わるサービスで、"
            "iOS / Android の両方に対応したいです。サーバー側の開発も含みます。",
            "業務の自動化ツールを作りたいです。基幹システムからデータを取り込み、"
            "帳票を出力する仕組みが必要です。開発できる会社を探しています。",
        ],
        "free": ["", "", "要件定義からお願いしたいです。"],
    },
    {
        "key": "sales_pitch",
        "weight": 2,
        "types": ["上記以外"],
        "budgets": ["50万円以下"],
        "deadlines": ["現時点では未定"],
        "pages": ["5ページ以下"],
        "status": "とりあえず早くサイトを作ってリリースしたい",
        "roles": ["営業部", "セールス担当", "事業開発"],
        "challenges": ["その他"],
        "messages": [
            "突然のご連絡失礼いたします。弊社はSEO対策サービスを提供しております。"
            "御社が制作されたサイトの検索順位改善にお役立ていただけます。"
            "一度30分ほどお時間をいただけませんでしょうか。",
            "いつもお世話になっております。弊社はオフショア開発のブリッジ支援を"
            "行っております。制作リソースの不足解消にお役立てできればと存じます。"
            "業務提携のご相談としてご連絡いたしました。",
            "はじめまして。弊社は制作会社様向けの受注支援プラットフォームを"
            "運営しております。掲載無料キャンペーンを実施中ですので、"
            "ぜひご検討いただけますと幸いです。",
            "ご担当者様。弊社の写真素材サービスのご案内です。"
            "Web制作でお使いいただける素材を定額でご利用いただけます。"
            "資料をお送りしてもよろしいでしょうか。",
        ],
        "free": ["", "", ""],
    },
    {
        "key": "implementation_only",
        "weight": 1,
        "types": ["実装のみ（Studio、Framer）"],
        "budgets": ["50万円", "100万円", "200万円"],
        "deadlines": ["1ヶ月以内", "2ヶ月以内"],
        "pages": ["5ページ以下", "6-10ページ"],
        "status": "作りたいサイトの構成などはある程度決まっていて、デザインにこだわりたい",
        "roles": ROLES_MID + ["デザイナー", "制作担当"],
        "challenges": ["Studioを使ってサイト制作をしたい", "Framerを使ってサイト制作をしたい"],
        "messages": [
            "社内で作成したFigmaのデザインを、Studioで実装していただきたいです。"
            "レスポンシブ対応込みでお願いします。CMSは必要ありません。",
            "デザインは完成しているので、Framerでの実装のみお願いしたいです。"
            "アニメーションの再現度を重視しています。スケジュールがタイトです。",
            "既存サイトをStudioに載せ替えたいです。デザインは現状を踏襲する前提で、"
            "実装と移行作業をお願いできますか。",
        ],
        "free": ["", "Figmaのリンクを共有できます。", ""],
    },
    {
        "key": "content_only",
        "weight": 1,
        "types": ["オウンドメディア"],
        "budgets": ["50万円", "100万円", "200万円"],
        "deadlines": ["2ヶ月以内", "3ヶ月以内", "半年以内"],
        "pages": ["11-20ページ", "21ページ以上"],
        "status": "とりあえず早くサイトを作ってリリースしたい",
        "roles": ROLES_MID + ROLES_STAFF,
        "challenges": ["コンテンツやデザイン、コピーの質を改善したい", "お問い合わせを増やしたい"],
        "messages": [
            "自社メディアの記事制作をお願いしたいです。月数本を継続的に"
            "書いていただける体制を探しています。サイト自体はすでにあるので、"
            "制作というよりライティングと編集の依頼になります。",
            "既存メディアのSEO改善をお願いできますか。記事のリライトと"
            "キーワード設計が中心になります。サイトの作り直しは考えていません。",
            "オウンドメディアの運用代行を探しています。記事の企画から入稿まで、"
            "月次で回していただけるとありがたいです。",
        ],
        "free": ["", "", ""],
    },
]

PAINS = [
    "10年以上更新しておらずスマートフォンで見づらい",
    "事業内容と掲載内容が合っていない",
    "採用候補者から分かりにくいと言われている",
    "問い合わせがほとんど入ってこない",
    "更新のたびに外注費が発生している",
    "競合と比べて見劣りする",
    "情報が増えすぎて整理できていない",
]

# 「{event}を進める」「{event}にあたり」に繋がる、事業上の出来事
EVENTS = [
    "ブランドの刷新",
    "新サービスの立ち上げ",
    "本社移転",
    "創業30周年",
    "新卒採用の開始",
    "事業の再編",
    "海外展開",
]

# 「{goal}を目指す」「{goal}が目的です」に繋がる、達成したいこと
GOALS = [
    "取引先への信頼感を高めること",
    "採用の母集団を広げること",
    "新サービスの立ち上げ",
    "ブランドの刷新",
    "問い合わせ件数を増やすこと",
    "事業内容を正しく伝えること",
]

NOTES = [
    "社内には更新を担当できる人員が1名います。",
    "ロゴとブランドガイドラインは別途制作中です。",
    "写真素材はこちらで用意できます。",
    "現在のサイトのアクセス解析データがあります。",
    "",
    "",
]

REFERRALS = [
    "検索エンジンで偶然見つけた",
    "他のウェブサイトで紹介されていた",
    "Studio Expertsサイトで知った",
    "Twitterで知った",
    "対談記事・ブログ記事で知った",
    "社内の人に教えてもらった",
    "社外の人に薦められた",
    "イベントで知った",
]

COMPARE = [
    "数社にお声がけして比較検討させていただく予定です。",
    "今月中に依頼先を決めたいと考えています。",
    "",
]


def generate(count: int, seed: int, start_index: int = 1) -> list[dict]:
    rng = random.Random(seed)
    pool = []
    for arch in ARCHETYPES:
        pool.extend([arch] * arch["weight"])

    # 同じ会社名が並ばないよう、使い切るまで引き直す
    companies = COMPANIES[:]
    rng.shuffle(companies)
    solos = SOLO_SENDERS[:]
    rng.shuffle(solos)

    def take_company():
        if not companies:
            companies.extend(COMPANIES)
            rng.shuffle(companies)
        return companies.pop()

    def take_solo():
        if not solos:
            solos.extend(SOLO_SENDERS)
            rng.shuffle(solos)
        return solos.pop()

    # 補足欄が自然につくのは、サイト制作として話が進んでいる相談だけ
    NOTE_OK = {"strong_lead", "warm", "implementation_only", "content_only"}
    # リニューアル前提になりうるアーキタイプ
    RENEWAL_OK = {"strong_lead", "warm", "implementation_only", "content_only"}

    rows = []
    for i in range(count):
        arch = rng.choice(pool)
        if arch["key"] in ("low_budget", "vague"):
            company, kind = take_solo()
            if company == "個人":
                company = kind
        else:
            company, _industry, kind = take_company()

        project_type = rng.choice(arch["types"])
        message = rng.choice(arch["messages"]).format(
            type=project_type,
            company_kind=kind,
            pain=rng.choice(PAINS),
            goal=rng.choice(GOALS),
            event=rng.choice(EVENTS),
            compare=rng.choice(COMPARE),
        ).strip()

        challenges = rng.sample(
            arch["challenges"], min(len(arch["challenges"]), rng.randint(1, 3))
        )

        rows.append({
            "id": f"GEN-{start_index + i:03d}",
            "received_at": f"2026-09-{rng.randint(1, 19):02d}",
            "name": _name(rng),
            "company": company,
            "email": "contact@example.co.jp",
            "project_type": project_type,
            "project_status": arch["status"],
            "challenges": CHALLENGE_SEPARATOR.join(challenges),
            "challenge_note": rng.choice(NOTES) if arch["key"] in NOTE_OK else "",
            "renewal_url": (
                "https://example.co.jp"
                if arch["key"] in RENEWAL_OK and rng.random() < 0.5
                else ""
            ),
            "pages": rng.choice(arch["pages"]),
            "budget": rng.choice(arch["budgets"]),
            "deadline": rng.choice(arch["deadlines"]),
            "referral": rng.choice(REFERRALS),
            "message": message,
            "free_text": rng.choice(arch["free"]),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="サンプルの問い合わせを生成する")
    ap.add_argument("--count", type=int, default=40, help="生成件数")
    ap.add_argument("--seed", type=int, default=7, help="乱数シード（同じ値なら同じ結果）")
    ap.add_argument("--start-index", type=int, default=1, help="IDの開始番号")
    ap.add_argument("--out", type=Path, required=True, help="書き出すCSVのパス")
    ap.add_argument("--append-to", type=Path, help="このCSVの内容を先頭に連結する")
    args = ap.parse_args()

    rows = []
    if args.append_to:
        with args.append_to.open(encoding="utf-8-sig", newline="") as fh:
            rows.extend(list(csv.DictReader(fh)))
    rows.extend(generate(args.count, args.seed, args.start_index))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS_ORDER)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} 件を書き出しました: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
