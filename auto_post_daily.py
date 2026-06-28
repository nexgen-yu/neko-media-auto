"""
auto_post_daily.py
毎日10記事を自動生成してWordPressに投稿するスクリプト
- Anthropic API (Claude Haiku) で記事生成
- WordPress REST API（Application Password認証）で投稿
- topics.json からトピックを順番に消費
- category フィールドに応じてプロンプトを切り替え
"""

import os
import json
import re
import requests
import anthropic
import datetime

# ============================================================
# 設定（GitHub Secrets から読み込む）
# ============================================================
WP_URL          = os.environ.get("WP_URL", "https://nexgen-service.com")
WP_USERNAME     = os.environ.get("WP_USERNAME", "nexgen")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "") or os.environ.get("WP_PASSWORD", "")
WP_API_BASE     = WP_URL.rstrip("/") + "/wp-json/wp/v2"
CLAUDE_API_KEY  = os.environ.get("CLAUDE_API_KEY", "")
AMAZON_TAG      = "nexgen0b-22"
POSTS_PER_RUN   = 10

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
        "extra": """- ペット保険の比較表（補償範囲・月額保険料・免責金額）を必ず含める\n- 実際の費用例（治療費vs保険料）を数字で示す\n- ペット保険加入率（約10%）など、読者の関心を引く統計を入れる""",
        "disclaimer": "※保険の適用条件や補償内容は各保険会社にご確認ください",
    },
    "犬の病気": {
        "persona": "犬の病気・健康管理に詳しい日本語ライターです",
        "extra": """- 症状の早見表（症状→考えられる病気→緊急度）をtableで作成\n- Amazon検索リンクのオレンジボタンを2〜3箇所""",
        "disclaimer": "※症状が続く場合は必ず獣医師にご相談ください",
    },
    "犬の健康": {
        "persona": "犬の健康管理・シニアケアに詳しい日本語ライターです",
        "extra": "- Amazon検索リンクのオレンジボタンを2〜3箇所",
        "disclaimer": "※症状が気になる場合は必ず獣医師にご相談ください",
    },
    "猫の病気": {
        "persona": "猫の病気・シニアケアに詳しい日本語ライターです",
        "extra": """- 症状の早見表（症状→考えられる病気→緊急度）をtableで作成\n- Amazon検索リンクのオレンジボタンを2〜3箇所""",
        "disclaimer": "※症状が続く場合は必ず獣医師にご相談ください",
    },
    "猫の健康": {
        "persona": "猫の健康管理・日常ケアに詳しい日本語ライターです",
        "extra": "- Amazon検索リンクのオレンジボタンを2〜3箇所",
        "disclaimer": "※症状が気になる場合は必ず獣医師にご相談ください",
    },
    "ペットと暮らす": {
        "persona": "ペットと人間の暮らし・ペットロスケアに詳しい日本語ライターです",
        "extra": "- Amazon検索リンクのオレンジボタンを1〜2箇所",
        "disclaimer": "※つらい気持ちが続く場合は専門家に相談することも大切です",
    },
}

DEFAULT_PROMPT_CONFIG = {
    "persona": "猫の腎臓病・シニアケアに詳しい日本語ライターです",
    "extra": "- Amazon検索リンクのオレンジボタンを2〜3箇所挿入する",
    "disclaimer": "※症状が気になる場合は必ず獣医師にご相談ください",
}

# ============================================================
# Claude Haiku で記事生成（区切り文字形式でJSONパースエラー回避）
# ============================================================
def generate_article(topic: dict) -> dict:
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    category = topic.get("category", "")
    cfg = CATEGORY_PROMPTS.get(category, DEFAULT_PROMPT_CONFIG)

    prompt = f"""あなたは{cfg["persona"]}。
以下のトピックについて、SEOに強いWordPress記事を書いてください。

トピック: {topic["title"]}
キーワード: {topic.get("keywords", topic["title"])}
カテゴリ: {category or "猫の腎臓ケア"}
Amazonアフィリエイトタグ: {AMAZON_TAG}

## 記事の要件
- 文字数: 1,500〜2,000字
- 見出し（h2・h3）を4〜6個使う。見出しテキストに番号を付けない
- 比較表（table）を1〜2個含める
{cfg["extra"]}
- よくある質問（FAQ）を3〜5問追加する
- WordPress Gutenberg ブロックコメント（wp:paragraph 等）でフォーマットする
- {cfg["disclaimer"]}

## 出力形式
以下の区切り文字を使って出力してください（JSONは使わない）:

===TITLE===
SEOタイトル（32字以内）
===CONTENT===
WordPress HTMLコンテンツ
===EXCERPT===
記事の概要（120字以内）
===END==="""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()

    title_match   = re.search(r'===TITLE===\s*(.*?)\s*===CONTENT===', raw, re.DOTALL)
    content_match = re.search(r'===CONTENT===\s*(.*?)\s*===EXCERPT===', raw, re.DOTALL)
    excerpt_match = re.search(r'===EXCERPT===\s*(.*?)(?:===END===|$)', raw, re.DOTALL)

    if not (title_match and content_match):
        raise ValueError(f"レスポンスのパースに失敗: {raw[:300]}")

    return {
        "title":   title_match.group(1).strip(),
        "content": content_match.group(1).strip(),
        "excerpt": excerpt_match.group(1).strip() if excerpt_match else "",
    }

# ============================================================
# WordPress REST API で投稿（Application Password認証）
# ============================================================
def post_to_wordpress(article: dict) -> int:
    url = f"{WP_API_BASE}/posts"
    payload = {
        "title":          article["title"],
        "content":        article["content"],
        "excerpt":        article.get("excerpt", ""),
        "status":         "publish",
        "comment_status": "open",
    }
    resp = requests.post(url, json=payload, auth=(WP_USERNAME, WP_APP_PASSWORD), timeout=60)
    resp.raise_for_status()
    return int(resp.json()["id"])

# ============================================================
# メイン処理
# ============================================================
def main():
    print(f"[{datetime.datetime.now()}] 自動投稿開始 — {POSTS_PER_RUN}記事")

    if not WP_APP_PASSWORD:
        print("[ERROR] WP_APP_PASSWORD が設定されていません")
        return
    if not CLAUDE_API_KEY:
        print("[ERROR] CLAUDE_API_KEY が設定されていません")
        return

    topics = get_pending_topics(POSTS_PER_RUN)
    if not topics:
        print("投稿待ちトピックがありません。")
        return

    success = 0
    errors  = 0

    for i, topic in enumerate(topics, 1):
        try:
            print(f"  [{i}/{len(topics)}] 生成中: {topic['title']}")
            article = generate_article(topic)
            post_id = post_to_wordpress(article)
            print(f"  投稿完了 — ID:{post_id} / {article['title']}")
            success += 1
        except Exception as e:
            print(f"  エラー: {topic['title']} — {e}")
            errors += 1

    print(f"\n完了: 成功{success}件 / エラー{errors}件")

if __name__ == "__main__":
    main()
