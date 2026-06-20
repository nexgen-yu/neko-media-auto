"""
猫健康メディア｜記事自動生成 & WordPress 投稿スクリプト v2
"""

import anthropic
import requests
import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
WP_URL = os.environ.get("WP_URL", "")
WP_USERNAME = os.environ.get("WP_USERNAME", "")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

KEYWORDS_FILE = Path(__file__).parent / "keywords.json"

CATEGORY_IDS = {
    "腎臓": 1, "シニア": 2, "フード": 3, "症状": 4,
    "予防": 5, "グッズ": 6, "サプリ": 7, "保険": 8, "猫種別": 9,
}

COMPARISON_PROMPT = """あなたは猫の健康と食事について詳しいペットメディアのライターです。
以下のキーワードでSEO最適化された記事を書いてください。

【メインキーワード】{keyword}
【文字数】約3,500字
【構成】
1. 導入（200字）
2. 基礎知識（700字）
3. 選び方のポイント（500字）
4. おすすめ商品5選（1,000字）
   ※「[商品名をAmazonで見る →](AMAZON_LINK_HERE)」の形式で記載
5. よくある質問 Q&A（400字）
6. まとめ（200字）

【トーン】専門的すぎず読みやすい文体。Markdown形式で出力。
最初の行は「# タイトル」。末尾に「*最終更新：{year}年{month}月*」"""

HOWTO_PROMPT = """あなたは猫の健康について詳しいペットメディアのライターです。
以下のキーワードでハウツー記事を書いてください。

【メインキーワード】{keyword}
【文字数】約2,500字
【構成】
1. 導入（100字）
2. 概要・なぜ重要か（400字）
3. 主な原因・種類（400字）
4. 対処法・ステップ（700字）
5. やってはいけないこと（300字）
6. 獣医師に相談するタイミング（200字）
7. まとめ（200字）

【トーン】不安を持つ飼い主に寄り添う。Markdown形式。見出しは##と###で。
最初の行は「# タイトル」。末尾に「*最終更新：{year}年{month}月*」"""


def load_keywords():
    with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_keywords(keywords):
    with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(keywords, f, ensure_ascii=False, indent=2)


def get_next_keyword(keywords):
    for i, item in enumerate(keywords):
        if item.get("status") == "pending":
            return i, item
    return None, None


def generate_article(keyword: str, article_type: str) -> tuple:
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    now = datetime.now()
    if article_type == "comparison":
        prompt = COMPARISON_PROMPT.format(keyword=keyword, year=now.year, month=now.month)
    else:
        prompt = HOWTO_PROMPT.format(keyword=keyword, year=now.year, month=now.month)
    print(f"Claude API で記事生成中: {keyword}")
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    content = message.content[0].text
    title = keyword
    for line in content.split("\n"):
        if line.startswith("# "):
            title = line.replace("# ", "").strip()
            break
    return title, content


def post_to_wordpress(title: str, content: str, category_id: int) -> dict:
    if not WP_URL:
        return {}
    credentials = base64.b64encode(f"{WP_USERNAME}:{WP_APP_PASSWORD}".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}", "Content-Type": "application/json"}
    data = {"title": title, "content": content, "status": "draft", "categories": [category_id]}
    try:
        response = requests.post(f"{WP_URL}/wp-json/wp/v2/posts", headers=headers, json=data, timeout=30)
        if response.status_code in [200, 201]:
            result = response.json()
            print(f"WordPress 投稿成功: ID={result['id']}")
            return result
        else:
            print(f"WordPress 投稿失敗: {response.status_code}")
            return {}
    except Exception as e:
        print(f"WordPress 接続エラー: {e}")
        return {}


def notify_slack(message: str):
    if not SLACK_WEBHOOK_URL:
        return
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=10)
    except Exception:
        pass


def save_to_file(title: str, content: str, keyword: str) -> str:
    safe_kw = keyword.replace(" ", "_")[:30]
    timestamp = datetime.now().strftime("%Y%m%d")
    filename = f"generated_{timestamp}_{safe_kw}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"ファイル保存: {filename}")
    return filename


def main():
    print(f"=== 猫健康メディア 記事自動生成 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    keywords = load_keywords()
    idx, item = get_next_keyword(keywords)
    if item is None:
        print("処理待ちのキーワードがありません。")
        sys.exit(0)
    kw = item["kw"]
    article_type = item.get("type", "howto")
    category = item.get("category", "その他")
    category_id = CATEGORY_IDS.get(category, 1)
    print(f"処理するキーワード: {kw} ({article_type})")
    title, content = generate_article(kw, article_type)
    filename = save_to_file(title, content, kw)
    wp_result = post_to_wordpress(title, content, category_id)
    keywords[idx]["status"] = "done"
    keywords[idx]["generated_at"] = datetime.now().strftime("%Y-%m-%d")
    keywords[idx]["wp_id"] = wp_result.get("id", "")
    keywords[idx]["title"] = title
    save_keywords(keywords)
    remaining = sum(1 for k in keywords if k.get("status") == "pending")
    notify_slack(f"✅ 記事生成完了\nKW: {kw}\nタイトル: {title}\nWP ID: {wp_result.get('id','N/A')}\n残り: {remaining}本")
    print(f"\n完了！残りキーワード: {remaining}本")


if __name__ == "__main__":
    main()
