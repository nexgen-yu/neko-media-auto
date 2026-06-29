"""
note.com 自動シンジケーション
WordPressの最新公開記事をnote.comにクロスポスト
実行方法: python note_syndication.py
GitHub Secrets: NOTE_EMAIL, NOTE_PASSWORD, NOTE_USER_URLNAME, WP_URL, WP_USERNAME, WP_APP_PASSWORD
依存: pip install requests playwright && playwright install --with-deps chromium
"""

import os
import re
import sys
import json
import time
import requests
from html.parser import HTMLParser
from pathlib import Path
from datetime import datetime, timezone

# 設定
WP_URL          = os.environ["WP_URL"]
WP_USERNAME     = os.environ["WP_USERNAME"]
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "") or os.environ.get("WP_PASSWORD", "")
WP_API_BASE     = WP_URL.rstrip("/") + "/wp-json/wp/v2"
NOTE_EMAIL      = os.environ["NOTE_EMAIL"]
NOTE_PASSWORD   = os.environ["NOTE_PASSWORD"]
NOTE_USER       = os.environ.get("NOTE_USER_URLNAME", "")

POSTED_IDS_FILE = "note_posted_ids.json"
MAX_POSTS_PER_RUN = 3
FOOTER_TEXT = "\n\n---\n※この記事はねこ腎ケアラボ（https://nexgen-service.com）からのシンジケーション記事です。"


# HTML→プレーンテキスト変換
class HTMLToText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []
        self.skip_tags = {"script", "style", "head"}
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self._skip = True
        if tag in ("p", "br", "h1", "h2", "h3", "h4", "li"):
            self.result.append("\n")
        if tag in ("h1", "h2", "h3"):
            self.result.append("■ ")

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self.result.append(data)

    def get_text(self):
        return re.sub(r"\n{3,}", "\n\n", "".join(self.result)).strip()


def html_to_text(html: str) -> str:
    parser = HTMLToText()
    parser.feed(html)
    return parser.get_text()


def get_wp_posts(count: int = 10) -> list:
    try:
        url = f"{WP_API_BASE}/posts"
        params = {
            "status": "publish",
            "per_page": min(count, 100),
            "orderby": "date",
            "order": "desc",
            "_fields": "id,title,link,content,date",
        }
        resp = requests.get(url, params=params, auth=(WP_USERNAME, WP_APP_PASSWORD), timeout=30)
        resp.raise_for_status()
        posts_raw = resp.json()
        posts = []
        for p in posts_raw:
            posts.append({
                "post_id":      str(p["id"]),
                "post_title":   p["title"]["rendered"],
                "post_content": p["content"]["rendered"],
                "link":         p["link"],
            })
        print(f"WP記事取得成功: {len(posts)}件")
        return posts
    except Exception as e:
        print(f"[ERROR] WP記事取得失敗: {e}")
        return []


def load_posted_ids() -> set:
    if Path(POSTED_IDS_FILE).exists():
        with open(POSTED_IDS_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_posted_ids(ids: set):
    with open(POSTED_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)


def note_login(email: str, password: str) -> requests.Session:
    """
    Playwrightのヘッドレスブラウザでnote.comにログインし
    セッションCookieをrequests.Sessionに移して返す。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "playwright未インストール: pip install playwright && playwright install --with-deps chromium"
        )

    print("Playwrightでnote.comにログイン中...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
        )
        page = context.new_page()

        try:
            page.goto("https://note.com/login?redirectPath=%2F", wait_until="networkidle", timeout=30000)
            print("  ログインページ読み込み完了")

            page.fill('input[placeholder="mail@example.com or note ID"]', email)
            page.fill('input[type="password"]', password)

            with page.expect_navigation(wait_until="networkidle", timeout=30000):
                page.click('button:has-text("ログイン")')

            current_url = page.url
            print(f"  ログイン後URL: {current_url}")

            if "login" in current_url:
                body_text = page.inner_text("body")[:300]
                raise RuntimeError(f"note.comログイン失敗: {body_text}")

            playwright_cookies = context.cookies()
            print(f"  note.comログイン成功: Cookie {len(playwright_cookies)}件取得")

        finally:
            browser.close()

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja,en;q=0.9",
    })
    for c in playwright_cookies:
        session.cookies.set(c["name"], c["value"], domain=c.get("domain", ".note.com"))

    return session


def post_to_note(session: requests.Session, title: str, body: str) -> dict:
    plain_body = html_to_text(body)
    plain_body = plain_body[:50000] + FOOTER_TEXT

    top_resp = session.get("https://note.com/", timeout=15)
    csrf_match = re.search(
        r"""<meta\s+name=["']csrf-token["']\s+content=["']([^"']+)["']""",
        top_resp.text,
    )
    csrf_token = csrf_match.group(1) if csrf_match else ""

    payload = {
        "name": title,
        "body": plain_body,
        "hashtag_names": ["猫の腎臓病", "シニア猫", "ペットの健康", "猫", "腎臓ケア"],
        "status": "published",
    }

    resp = session.post(
        "https://note.com/api/v1/text_notes",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Referer": "https://note.com/n/new",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": csrf_token,
        },
        timeout=30,
    )

    if resp.status_code in (200, 201):
        data = resp.json()
        note_url = f"https://note.com/n/{data.get('data', {}).get('key', '')}"
        print(f"  note投稿成功: {title[:40]} -> {note_url}")
        return data
    else:
        print(f"  note投稿失敗: {resp.status_code} {resp.text[:300]}")
        resp.raise_for_status()


def main():
    print(f"=== note.com自動シンジケーション {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")

    posted_ids = load_posted_ids()
    print(f"投稿済みWP記事ID数: {len(posted_ids)}")

    wp_posts = get_wp_posts(count=20)
    print(f"WP最新記事取得: {len(wp_posts)}件")

    if not wp_posts:
        print("[ERROR] WP記事が取得できませんでした。終了。")
        sys.exit(1)

    new_posts = [p for p in wp_posts if str(p["post_id"]) not in posted_ids]
    print(f"未投稿記事: {len(new_posts)}件 -> 最大{MAX_POSTS_PER_RUN}件を投稿")

    if not new_posts:
        print("新規投稿対象なし。終了。")
        return

    session = note_login(NOTE_EMAIL, NOTE_PASSWORD)

    targets = new_posts[:MAX_POSTS_PER_RUN]
    success_ids = set()
    for post in targets:
        wp_id = str(post["post_id"])
        title = post["post_title"]
        body  = post["post_content"]
        print(f"\n投稿中: [{wp_id}] {title[:50]}")
        try:
            post_to_note(session, title, body)
            success_ids.add(wp_id)
            time.sleep(5)
        except Exception as e:
            print(f"  エラー: {e}")

    posted_ids |= success_ids
    save_posted_ids(posted_ids)
    print(f"\n完了: {len(success_ids)}/{len(targets)}件投稿成功")


if __name__ == "__main__":
    main()
