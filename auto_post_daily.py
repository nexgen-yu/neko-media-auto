"""
auto_post_daily.py
毎日10記事を自動生成してWordPressに投稿するスクリプト
- Anthropic API (Claude Haiku) で記事生成
- WordPress XML-RPC で投稿（Xserver対応：Authヘッダー不要）
- topics.json からトピックを順番に消費
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
# Claude Haiku で記事生成
# ============================================================
def generate_article(topic: dict) -> dict:
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    prompt = f"""あなたは猫の腎臓病・シニアケアに詳しい日本語ライターです。
以下のトピックについて、SEOに強いWordPress記事を書いてください。

トピック: {topic["title"]}
キーワード: {topic.get("keywords", topic["title"])}
Amazonアフィリエイトタグ: {AMAZON_TAG}

## 記事の要件
- 文字数: 1,000〜1,500字
- 見出し（h2・h3）を3〜5個使う
- 比較表（table）を1〜2個含める
- Amazon検索リンクのオレンジボタンを2〜3箇所挿入する
  形式: <a href="https://www.amazon.co.jp/s?k={{検索ワード}}&tag={AMAZON_TAG}" target="_blank" rel="noopener" style="display:inline-block;background:#ff9900;color:#fff;padding:8px 16px;border-radius:4px;text-decoration:none;font-weight:bold;">Amazonで見る</a>
- よくある質問（FAQ）を2〜3問追加する
- WordPress Gutenberg ブロックコメント（<!-- wp:paragraph --> 等）でフォーマットする
- 医療情報は「獣医師に相談してください」を必ず添える

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
        print("投稿待ちトピックがありません。topics.json に追加してください。")
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
