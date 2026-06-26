"""
x_auto_post.py
新記事をX（Twitter）に自動投稿する

必要なGitHub Secrets:
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
  WP_URL, WP_USERNAME, WP_PASSWORD, CLAUDE_API_KEY

使い方:
  python x_auto_post.py              # 未投稿記事を最大3件投稿
  python x_auto_post.py --limit 1    # 最大1件
  python x_auto_post.py --dry-run    # 確認のみ（ポストしない）
"""

import os
import sys
import json
import time
import xmlrpc.client
import anthropic
import argparse
from bs4 import BeautifulSoup

try:
    import tweepy
except ImportError:
    print("[ERROR] tweepy がインストールされていません: pip install tweepy")
    sys.exit(1)

WP_URL      = os.environ.get("WP_URL", "https://nexgen-service.com")
WP_USERNAME = os.environ.get("WP_USERNAME", "nexgen")
WP_PASSWORD = os.environ.get("WP_PASSWORD", "")
XMLRPC_URL  = WP_URL.rstrip("/") + "/xmlrpc.php"

CLAUDE_API_KEY        = os.environ.get("CLAUDE_API_KEY", "")
X_API_KEY             = os.environ.get("X_API_KEY", "")
X_API_SECRET          = os.environ.get("X_API_SECRET", "")
X_ACCESS_TOKEN        = os.environ.get("X_ACCESS_TOKEN", "")
X_ACCESS_TOKEN_SECRET = os.environ.get("X_ACCESS_TOKEN_SECRET", "")

POSTED_IDS_FILE = os.path.join(os.path.dirname(__file__), "x_posted_ids.json")
DEFAULT_HASHTAGS = "#猫 #シニア猫 #猫のいる生活 #猫の健康"


def load_posted_ids() -> set:
    if os.path.exists(POSTED_IDS_FILE):
        with open(POSTED_IDS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_posted_ids(ids: set):
    with open(POSTED_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)


def generate_tweet(title: str, body_text: str, url: str, client: anthropic.Anthropic) -> str:
    excerpt = body_text[:400].strip()
    prompt = f"""以下のブログ記事をXに投稿するための文章を作成してください。

【条件】
- 絵文字を1〜2個使って親しみやすく
- 記事の価値・読むべき理由を1文で伝える
- URLとハッシュタグは自分で書かない
- 本文のみ出力（説明や前置き不要）
- 最大100文字

【タイトル】
{title}

【本文冒頭】
{excerpt}

投稿文:"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}]
    )
    body = message.content[0].text.strip()
    tweet = f"{body}\n\n{url}\n{DEFAULT_HASHTAGS}"
    if len(tweet) > 280:
        max_body = 280 - len(f"\n\n{url}\n{DEFAULT_HASHTAGS}") - 3
        body = body[:max_body] + "..."
        tweet = f"{body}\n\n{url}\n{DEFAULT_HASHTAGS}"
    return tweet


def get_recent_posts(wp: xmlrpc.client.ServerProxy, n: int = 50) -> list:
    try:
        return wp.wp.getPosts(1, WP_USERNAME, WP_PASSWORD, {
            "post_status": "publish",
            "number": n,
            "post_type": "post",
            "orderby": "date",
            "order": "DESC",
        })
    except Exception as e:
        print(f"[ERROR] WP記事取得失敗: {e}")
        return []


def post_to_x(tweet_text: str) -> bool:
    try:
        client = tweepy.Client(
            consumer_key=X_API_KEY,
            consumer_secret=X_API_SECRET,
            access_token=X_ACCESS_TOKEN,
            access_token_secret=X_ACCESS_TOKEN_SECRET,
        )
        response = client.create_tweet(text=tweet_text)
        tweet_id = response.data["id"]
        print(f"  post: https://x.com/i/web/status/{tweet_id}")
        return True
    except Exception as e:
        print(f"  [ERROR] X投稿失敗: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",   type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    missing = []
    if not WP_PASSWORD:           missing.append("WP_PASSWORD")
    if not CLAUDE_API_KEY:        missing.append("CLAUDE_API_KEY")
    if not X_API_KEY:             missing.append("X_API_KEY")
    if not X_API_SECRET:          missing.append("X_API_SECRET")
    if not X_ACCESS_TOKEN:        missing.append("X_ACCESS_TOKEN")
    if not X_ACCESS_TOKEN_SECRET: missing.append("X_ACCESS_TOKEN_SECRET")

    if missing and not args.dry_run:
        print(f"[ERROR] 未設定: {', '.join(missing)}")
        sys.exit(1)

    wp     = xmlrpc.client.ServerProxy(XMLRPC_URL)
    claude = anthropic.Anthropic(api_key=CLAUDE_API_KEY) if CLAUDE_API_KEY else None

    posted_ids = load_posted_ids()
    print(f"=== X自動投稿スクリプト ===")
    print(f"投稿済み: {len(posted_ids)}件")

    posts     = get_recent_posts(wp)
    new_posts = [p for p in reversed(posts) if int(p["post_id"]) not in posted_ids]
    print(f"未投稿: {len(new_posts)}件")

    if not new_posts:
        print("投稿する新記事がありません")
        return

    success = fail = 0

    for post in new_posts[:args.limit]:
        post_id   = int(post["post_id"])
        title     = post.get("post_title", "").strip()
        content   = post.get("post_content", "")
        url       = post.get("link", f"{WP_URL}/?p={post_id}")
        soup      = BeautifulSoup(content, "html.parser")
        body_text = soup.get_text(separator=" ", strip=True)

        print(f"\nID={post_id} 「{title[:30]}」")

        if claude:
            tweet_text = generate_tweet(title, body_text, url, claude)
        else:
            tweet_text = f"新記事: {title}\n\n{url}\n{DEFAULT_HASHTAGS}"

        print(f"  投稿文 ({len(tweet_text)}文字): {tweet_text[:80]}...")

        if args.dry_run:
            print("  [DRY-RUN]")
            posted_ids.add(post_id)
            success += 1
            continue

        ok = post_to_x(tweet_text)
        if ok:
            posted_ids.add(post_id)
            save_posted_ids(posted_ids)
            success += 1
        else:
            fail += 1

        time.sleep(60)

    print(f"\n=== 完了: 成功{success} / 失敗{fail} ===")


if __name__ == "__main__":
    main()
