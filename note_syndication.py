"""
note.com 自動シンジケーション
WordPressの最新公開記事をnote.comにクロスポスト
実行方法: python note_syndication.py
GitHub Secrets: NOTE_EMAIL, NOTE_PASSWORD, NOTE_USER_URLNAME, WP_URL, WP_USERNAME, WP_PASSWORD
"""

import os
import re
import sys
import json
import time
import xmlrpc.client
import requests
from html.parser import HTMLParser
from pathlib import Path
from datetime import datetime, timezone

# ─── 設定 ────────────────────────────────────────────
WP_URL       = os.environ["WP_URL"]
WP_USERNAME  = os.environ["WP_USERNAME"]
WP_PASSWORD  = os.environ["WP_PASSWORD"]
NOTE_EMAIL   = os.environ["NOTE_EMAIL"]
NOTE_PASSWORD= os.environ["NOTE_PASSWORD"]
NOTE_USER    = os.environ.get("NOTE_USER_URLNAME", "")  # note.comのURLname（任意）

# 投稿済みWP記事IDを記録するファイル
POSTED_IDS_FILE = "note_posted_ids.json"

# 1回の実行で最大いくつWP記事をnoteに投稿するか
MAX_POSTS_PER_RUN = 3

# note.comに投稿する際の末尾テキスト
FOOTER_TEXT = "\n\n---\n※この記事はねこ腎ケアラボ（https://nexgen-service.com）からのシンジケーション記事です。"


# ─── HTMLをプレーンテキストへ変換 ────────────────────
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


# ─── WordPress から最新記事取得 ──────────────────────
def get_wp_posts(count: int = 10) -> list:
    client = xmlrpc.client.ServerProxy(f"{WP_URL}/xmlrpc.php")
    posts = client.wp.getPosts(
        1, WP_USERNAME, WP_PASSWORD,
        {
            "post_type": "post",
            "post_status": "publish",
            "number": count,
            "orderby": "date",
            "order": "DESC",
        }
    )
    return posts


def load_posted_ids() -> set:
    if Path(POSTED_IDS_FILE).exists():
        with open(POSTED_IDS_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_posted_ids(ids: set):
    with open(POSTED_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)


# ─── note.com ログイン ───────────────────────────────
def note_login(email: str, password: str) -> requests.Session:
    """
    note.comにrequestsでログインしてセッションを返す。
    CSRF tokenはログインページのmetaタグから取得。
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "ja,en;q=0.9",
    })

    # ログインページからCSRFトークン取得
    login_page = session.get("https://note.com/login?redirectPath=%2F", timeout=15)
    login_page.raise_for_status()

    # meta[name=csrf-token] を探す
    csrf_match = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', login_page.text)
    if not csrf_match:
        # alternate: APIベースのログイン（CSRF不要の場合）
        csrf_token = ""
    else:
        csrf_token = csrf_match.group(1)

    # セッションID（ページのCookieから）
    session_id = session.cookies.get("_note_session_v2", "")

    # ログインAPI呼び出し
    resp = session.post(
        "https://note.com/api/v1/sessions/sign_in",
        json={"login": email, "password": password},
        headers={
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf_token,
            "Referer": "https://note.com/login",
        },
        timeout=15,
    )

    if resp.status_code == 200:
        data = resp.json()
        if data.get("data", {}).get("user_id"):
            print(f"✅ note.comログイン成功: user_id={data['data']['user_id']}")
            return session
        else:
            print(f"⚠️  ログインレスポンス異常: {resp.text[:200]}")

    # フォールバック: 旧ログインエンドポイント
    resp2 = session.post(
        "https://note.com/api/v1/sessions",
        json={"login": email, "password": password},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    if resp2.status_code in (200, 201):
        print("✅ note.comログイン成功（フォールバック）")
        return session

    raise RuntimeError(f"note.comログイン失敗: {resp2.status_code} {resp2.text[:300]}")


# ─── note.com に記事投稿 ─────────────────────────────
def post_to_note(session: requests.Session, title: str, body: str) -> dict:
    """
    テキストノートをnote.comに投稿（公開）。
    成功したらレスポンスJSONを返す。
    """
    # WPのHTML本文をプレーンテキストに変換
    plain_body = html_to_text(body)
    # note.comの文字数制限（約10万字）に合わせてカット
    plain_body = plain_body[:50000] + FOOTER_TEXT

    payload = {
        "name": title,
        "body": plain_body,
        "hashtag_names": ["猫の腎臓病", "シニア猫", "ペットの健康", "猫", "腎臓ケア"],
        "status": "published",  # "draft" にすれば下書き保存
    }

    resp = session.post(
        "https://note.com/api/v1/text_notes",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Referer": "https://note.com/n/new",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
    )

    if resp.status_code in (200, 201):
        data = resp.json()
        note_url = f"https://note.com/n/{data.get('data', {}).get('key', '')}"
        print(f"  ✅ note投稿成功: {title[:40]} → {note_url}")
        return data
    else:
        print(f"  ❌ note投稿失敗: {resp.status_code} {resp.text[:300]}")
        resp.raise_for_status()


# ─── カテゴリ別ハッシュタグ ──────────────────────────
CATEGORY_TAGS = {
    "猫の腎臓病": ["猫の腎臓病", "シニア猫", "腎臓ケア", "猫", "CKD"],
    "猫の病気": ["猫の病気", "猫の健康", "猫", "ペット"],
    "猫の健康": ["猫の健康", "シニア猫", "猫", "ペット"],
    "犬の病気": ["犬の病気", "犬の健康", "犬", "ペット"],
    "犬の健康": ["犬の健康", "犬", "ペット"],
    "ペット保険": ["ペット保険", "猫保険", "犬保険", "ペット"],
    "ペットと暮らす": ["ペットと暮らす", "猫", "犬", "ペット"],
}


def get_tags_for_post(post: dict) -> list:
    for cat in post.get("terms", {}).get("category", []):
        cat_name = cat.get("name", "")
        if cat_name in CATEGORY_TAGS:
            return CATEGORY_TAGS[cat_name]
    return ["猫", "ペット", "ペットの健康"]


# ─── メイン処理 ──────────────────────────────────────
def main():
    print(f"=== note.com自動シンジケーション {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")

    # 投稿済みIDロード
    posted_ids = load_posted_ids()
    print(f"投稿済みWP記事ID数: {len(posted_ids)}")

    # WP記事取得
    wp_posts = get_wp_posts(count=20)
    print(f"WP最新記事取得: {len(wp_posts)}件")

    # 未投稿のものだけ絞り込む
    new_posts = [p for p in wp_posts if str(p["post_id"]) not in posted_ids]
    print(f"未投稿記事: {len(new_posts)}件 → 最大{MAX_POSTS_PER_RUN}件を投稿")

    if not new_posts:
        print("新規投稿対象なし。終了。")
        return

    # note.comにログイン
    session = note_login(NOTE_EMAIL, NOTE_PASSWORD)

    # 投稿
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
            time.sleep(5)  # レート制限対策
        except Exception as e:
            print(f"  エラー: {e}")

    # 投稿済みID保存
    posted_ids |= success_ids
    save_posted_ids(posted_ids)
    print(f"\n完了: {len(success_ids)}/{len(targets)}件投稿成功")


if __name__ == "__main__":
    main()
