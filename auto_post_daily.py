"""
auto_post_daily.py
毎日10記事を自動生成してWordPressに投稿するスクリプト
- Anthropic API (Claude Haiku) で記事生成
- WordPress XML-RPC で投稿（Xserver対応：Authヘッダー不要）
- topics.json からトピックを順番に消費
- category フィールドに応じてプロンプトを切り替え（猫腎臓／猫一般／犬健康／ペット保険）
"""

import os
import json
import xmlrpc.client
import anthropic
import datetime
import random

# ============================================================
# 設定（GitHub Secrets から読み込む）
# ============================================================
WP_URL       = os.environ.get("WP_URL", "https://nexgen-service.com")
WP_USERNAME  = os.environ.get("WP_USERNAME", "nexgen")
WP_PASSWORD  = os.environ.get("WP_PASSWORD", "")           # GitHub Secret: WP_PASSWORD
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")      # GitHub Secret: CLAUDE_API_KEY
AMAZON_TAG   = "nexgen0b-22"
POSTS_PER_RUN = 10                                          # 1回あたりの投稿数

# ============================================================
# トピックリスト読み込み
# ============================================================
TOPICS_FILE = os.path.join(os.path.dirname(__file__), "topics.json")

def load_topics():
    with open(TOPICS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_topics(data):
    with open(TOPICS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_pending_topics(count=10):
    data = load_topics()
    pending = [t for t in data["topics"] if not t.get("posted")]
    selected = pending[:count]
    # 使用済みにマーク
    used_titles = {t["title"] for t in selected}
    for t in data["topics"]:
        if t["title"] in used_titles:
            t["posted"] = True
            t["posted_date"] = datetime.datetime.now().isoformat()
    save_topics(data)
    return selected

# ============================================================
# カテゴリ別プロンプト設定
# ============================================================
CATEGORY_PROMPTS = {
    "ペット保険": {
        "persona": "ペット保険の比較・節約に詳しい日本語ライターです",
        "extra": """- ペット保険の比較表（補償範囲・月額保険料・免責金額）を必ず含める
- 実際の費用例（治療費vs保険料）を数字で示す
- 「今すぐ資料請求」「無料見積もり」等のCTAをAmazonボタンの代わりに設置する場合は以下を使用:
  <a href="https://px.a8.net/svt/ejp?a8mat=【省略・テンプレ用】" target="_blank" rel="nofollow noopener" style="display:inline-block;background:#e74c3c;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold;">🐾 無料でペット保険を比較する</a>
- ペット保険加入率（約10%）など、読者の関心を引く統計を入れる""",
        "disclaimer": "※保険の適用条件や補償内容は各保険会社にご確認ください",
    },
    "犬の病気": {
        "persona": "犬の病気・健康管理に詳しい日本語ライターです",
        "extra": """- 症状の早見表（症状→考えられる病気→緊急度）をtableで作成
- 「すぐ病院へ」「様子見OK」の判断基準を明確に示す
- Amazon検索リンクのオレンジボタンを2〜3箇所（関連サプリ・療法食等）""",
        "disclaimer": "※症状が続く場合は必ず獣医師にご相談ください",
    },
    "犬の健康": {
        "persona": "犬の健康管理・シニアケアに詳しい日本語ライターです",
        "extra": """- 犬種別・年齢別の具体的なアドバイスを含める
- Amazon検索リンクのオレンジボタンを2〜3箇所（ケアグッズ・フード等）
- 日常ケアのチェックリストをHTML listで作成""",
        "disclaimer": "※症状が気になる場合は必ず獣医師にご相談ください",
    },
    "猫の病気": {
        "persona": "猫の病気・シニアケアに詳しい日本語ライターです",
        "extra": """- 症状の早見表（症状→考えられる病気→緊急度）をtableで作成
- 「すぐ病院へ」「様子見OK」の判断基準を明確に示す
- Amazon検索リンクのオレンジボタンを2〜3箇所（関連サプリ・療法食等）""",
        "disclaimer": "※症状が続く場合は必ず獣医師にご相談ください",
    },
    "猫の健康": {
        "persona": "猫の健康管理・日常ケアに詳しい日本語ライターです",
        "extra": """- 年齢別（子猫・成猫・シニア猫）のアドバイスを必要に応じて含める
- Amazon検索リンクのオレンジボタンを2〜3箇所（ケアグッズ・フード等）
- 実践的なコツや注意点をリスト形式で""",
        "disclaimer": "※症状が気になる場合は必ず獣医師にご相談ください",
    },
    "ペットと暮らす": {
        "persona": "ペットと人間の暮らし・ペットロスケアに詳しい日本語ライターです",
        "extra": """- 体験談調の共感できる書き出しで読者の心に寄り添う
- Amazon検索リンクのオレンジボタンを1〜2箇所（メモリアルグッズ・書籍等）
- 専門機関・相談窓口への誘導を末尾に添える""",
        "disclaimer": "※つらい気持ちが続く場合は専門家に相談することも大切です",
    },
}

DEFAULT_PROMPT_CONFIG = {
    "persona": "猫の腎臓病・シニアケアに詳しい日本語ライターです",
    "extra": """- Amazon検索リンクのオレンジボタンを2〜3箇所挿入する
  形式: <a href="https://www.amazon.co.jp/s?k={{検索ワード}}&tag={AMAZON_TAG}" target="_blank" rel="noopener" style="display:inline-block;background:#ff9900;color:#fff;padding:8px 16px;border-radius:4px;text-decoration:none;font-weight:bold;">Amazonで見る</a>""",
    "disclaimer": "※症状が気になる場合は必ず獣医師にご相談ください",
}


# ============================================================
# Claude Haiku で記事生成
# ============================================================
def generate_article(topic: dict) -> dict:
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    category = topic.get("category", "")
    cfg = CATEGORY_PROMPTS.get(category, DEFAULT_PROMPT_CONFIG)

    amazon_btn = (
        f'<a href="https://www.amazon.co.jp/s?k={{検索ワード}}&tag={AMAZON_TAG}" '
        f'target="_blank" rel="noopener" style="display:inline-block;background:#ff9900;'
        f'color:#fff;padding:8px 16px;border-radius:4px;text-decoration:none;font-weight:bold;">Amazonで見る</a>'
    )

    prompt = f"""あなたは{cfg["persona"]}。
以下のトピックについて、SEOに強いWordPress記事を書いてください。

トピック: {topic["title"]}
キーワード: {topic.get("keywords", topic["title"])}
カテゴリ: {category or "猫の腎臓ケア"}
Amazonアフィリエイトタグ: {AMAZON_TAG}

## 記事の要件
- 文字数: 1,500〜2,000字
- 見出し（h2・h3）を4〜6個使う。**見出しテキストに番号（1. 2. など）を付けない**（TOCプラグインが自動採番するため重複になる）
- 比較表（table）を1〜2個含める
{cfg["extra"]}
- よくある質問（FAQ）を3〜5問追加する
- WordPress Gutenberg ブロックコメント（<!-- wp:paragraph --> 等）でフォーマットする
- {cfg["disclaimer"]}

## 出力形式
JSON形式で以下を返してください:
{{
  "title": "SEOタイトル（32字以内）",
  "content": "WordPress HTMLコンテンツ",
  "excerpt": "記事の概要（120字以内）"
}}

JSONのみを出力し、前後に説明文を付けないでください。"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    # JSON部分だけ抽出（```json ... ``` の場合に対応）
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)

# ============================================================
# WordPress XML-RPC で投稿
# ============================================================
def post_to_wordpress(article: dict) -> int:
    wp = xmlrpc.client.ServerProxy(f"{WP_URL}/xmlrpc.php", allow_none=True)

    post = {
        "post_title":   article["title"],
        "post_content": article["content"],
        "post_excerpt": article.get("excerpt", ""),
        "post_status":  "publish",
        "post_author":  "1",
        "comment_status": "open",
    }

    post_id = wp.wp.newPost(
        "1",           # blog_id
        WP_USERNAME,
        WP_PASSWORD,
        post
    )
    return int(post_id)

# ============================================================
# メイン処理
# ============================================================
def main():
    print(f"[{datetime.datetime.now()}] 自動投稿開始 — {POSTS_PER_RUN}記事")

    topics = get_pending_topics(POSTS_PER_RUN)
    if not topics:
        print("⚠️  投稿待ちトピックがありません。topics.json に追加してください。")
        return

    success = 0
    errors  = 0

    for i, topic in enumerate(topics, 1):
        try:
            print(f"  [{i}/{len(topics)}] 生成中: {topic['title']}")
            article = generate_article(topic)
            post_id = post_to_wordpress(article)
            print(f"  ✅ 投稿完了 — ID:{post_id} / {article['title']}")
            success += 1
        except Exception as e:
            print(f"  ❌ エラー: {topic['title']} — {e}")
            errors += 1

    print(f"\n完了: 成功{success}件 / エラー{errors}件")

if __name__ == "__main__":
    main()
