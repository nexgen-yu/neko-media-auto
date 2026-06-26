"""
insert_affiliate_links.py
新記事（ID81以降）にAmazonアフィリエイトリンクを自動挿入する

フロー:
1. 対象記事を取得
2. 記事タイトル・本文からキーワード抽出
3. Amazon検索URLアフィリエイトリンクボタンを生成
4. 記事内の適切な位置（冒頭・中盤・末尾）に挿入
5. XML-RPCで記事を更新

使い方:
  python insert_affiliate_links.py              # ID81以降の全記事
  python insert_affiliate_links.py --ids 81 82  # 指定IDのみ
  python insert_affiliate_links.py --dry-run    # 確認のみ
"""

import os
import sys
import re
import time
import xmlrpc.client
import argparse
from bs4 import BeautifulSoup

WP_URL      = os.environ.get("WP_URL", "https://nexgen-service.com")
WP_USERNAME = os.environ.get("WP_USERNAME", "nexgen")
WP_PASSWORD = os.environ.get("WP_PASSWORD", "")
XMLRPC_URL  = WP_URL.rstrip("/") + "/xmlrpc.php"
AMAZON_TAG  = "nexgen0b-22"

MIN_POST_ID = 81

AFFILIATE_RULES = [
    {
        "keywords": ["腎臓", "腎不全", "CKD", "慢性腎臓病"],
        "products": [
            {"label": "腎臓ケア療法食",      "query": "猫+腎臓ケア+療法食"},
            {"label": "腎臓サポートサプリ",  "query": "猫+腎臓+サプリメント"},
        ],
    },
    {
        "keywords": ["フード", "食事", "食べ", "ご飯", "ウェット", "ドライ"],
        "products": [
            {"label": "シニア猫用フード",    "query": "シニア猫+フード+低リン"},
            {"label": "ウェットフード",      "query": "猫+ウェットフード+シニア"},
        ],
    },
    {
        "keywords": ["水分", "水を飲", "脱水", "給水"],
        "products": [
            {"label": "自動給水器",          "query": "猫+自動給水器+ろ過"},
        ],
    },
    {
        "keywords": ["サプリ", "サプリメント", "栄養"],
        "products": [
            {"label": "猫用総合サプリ",      "query": "猫+サプリメント+シニア+栄養"},
        ],
    },
    {
        "keywords": ["保険", "ペット保険", "医療費"],
        "products": [
            {"label": "ペット保険を比較",    "query": "猫+ペット保険+シニア+比較"},
        ],
    },
    {
        "keywords": ["おもちゃ", "遊び", "運動", "ストレス"],
        "products": [
            {"label": "猫用おもちゃ",        "query": "猫+おもちゃ+シニア+運動"},
        ],
    },
]

DEFAULT_PRODUCTS = [
    {"label": "シニア猫向け商品一覧", "query": "シニア猫+健康+おすすめ"},
]

AMAZON_BUTTON_TEMPLATE = (
    '<a href="https://www.amazon.co.jp/s?k={query}&tag={tag}" '
    'target="_blank" rel="noopener" '
    'style="display:inline-block;background:#ff9900;color:#fff;'
    'padding:10px 20px;border-radius:6px;text-decoration:none;'
    'font-weight:bold;font-size:15px;margin:10px 4px;">'
    '🛒 Amazonで{label}を見る</a>'
)

AFFILIATE_BLOCK_TEMPLATE = """
<!-- wp:group {"className":"affiliate-links-box"} -->
<div class="wp-block-group affiliate-links-box" style="background:#fff8e1;border:2px solid #ff9900;border-radius:8px;padding:16px;margin:24px 0;">
<!-- wp:paragraph {"style":{"typography":{"fontWeight":"bold"}}} -->
<p><strong>🛒 おすすめ商品をAmazonでチェック</strong></p>
<!-- /wp:paragraph -->
<!-- wp:paragraph -->
<p>{buttons}</p>
<!-- /wp:paragraph -->
</div>
<!-- /wp:group -->
"""


def already_has_affiliate(content: str) -> bool:
    return "affiliate-links-box" in content or (AMAZON_TAG in content and "amazon.co.jp" in content)


def select_products(title: str, body_text: str) -> list:
    combined = title + " " + body_text[:800]
    matched = []
    for rule in AFFILIATE_RULES:
        if any(kw in combined for kw in rule["keywords"]):
            matched.extend(rule["products"])
    return matched[:3] if matched else DEFAULT_PRODUCTS[:2]


def build_affiliate_block(products: list) -> str:
    buttons = ""
    for p in products:
        query = p["query"].replace(" ", "+")
        buttons += AMAZON_BUTTON_TEMPLATE.format(query=query, tag=AMAZON_TAG, label=p["label"])
    return AFFILIATE_BLOCK_TEMPLATE.format(buttons=buttons)


def insert_at_positions(content: str, block: str) -> str:
    new_content = content.rstrip() + "\n" + block
    heading_pattern = re.compile(r'(<!-- /wp:heading -->)', re.IGNORECASE)
    matches = list(heading_pattern.finditer(new_content))
    if matches:
        first_match = matches[0]
        insert_pos = first_match.end()
        if insert_pos < len(new_content) * 0.7:
            new_content = new_content[:insert_pos] + "\n" + block + new_content[insert_pos:]
    return new_content


def get_posts_by_ids(wp, post_ids: list) -> list:
    posts = []
    for pid in post_ids:
        try:
            post = wp.wp.getPost(1, WP_USERNAME, WP_PASSWORD, pid)
            if post.get("post_status") == "publish":
                posts.append(post)
        except Exception as e:
            print(f"  [WARN] ID={pid} 取得失敗: {e}")
    return posts


def get_posts_from_id(wp, min_id: int) -> list:
    all_posts = []
    offset = 0
    per_page = 50
    while True:
        batch = wp.wp.getPosts(1, WP_USERNAME, WP_PASSWORD, {
            "post_status": "publish",
            "number": per_page,
            "offset": offset,
            "post_type": "post",
            "orderby": "ID",
            "order": "ASC",
        })
        if not batch:
            break
        for p in batch:
            if int(p["post_id"]) >= min_id:
                all_posts.append(p)
        if len(batch) < per_page:
            break
        offset += per_page
    return all_posts


def update_post_content(wp, post_id: int, new_content: str) -> bool:
    try:
        result = wp.wp.editPost(1, WP_USERNAME, WP_PASSWORD, post_id, {
            "post_content": new_content,
        })
        return bool(result)
    except Exception as e:
        print(f"  [ERROR] ID={post_id} 更新失敗: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids",     nargs="*", type=int, help="対象post IDを指定")
    parser.add_argument("--dry-run", action="store_true", help="更新せずに確認のみ")
    args = parser.parse_args()

    if not WP_PASSWORD:
        print("[ERROR] WP_PASSWORD が未設定です")
        sys.exit(1)

    wp = xmlrpc.client.ServerProxy(XMLRPC_URL)

    print("=== アフィリエイトリンク自動挿入スクリプト ===")
    print(f"対象サイト: {WP_URL}")

    if args.ids:
        print(f"指定ID: {args.ids}")
        posts = get_posts_by_ids(wp, args.ids)
    else:
        print(f"ID {MIN_POST_ID} 以降の記事を取得中...")
        posts = get_posts_from_id(wp, MIN_POST_ID)

    print(f"対象記事数: {len(posts)}")

    success = skip = fail = 0

    for post in posts:
        post_id = int(post["post_id"])
        title   = post.get("post_title", "").strip()
        content = post.get("post_content", "")

        print(f"\n処理中 ID={post_id} 「{title[:30]}」")

        if already_has_affiliate(content):
            print(f"  [SKIP] 既にアフィリエイトリンクあり")
            skip += 1
            continue

        soup      = BeautifulSoup(content, "html.parser")
        body_text = soup.get_text(separator=" ", strip=True)

        products = select_products(title, body_text)
        print(f"  商品選定: {[p['label'] for p in products]}")

        block = build_affiliate_block(products)
        new_content = insert_at_positions(content, block)

        if args.dry_run:
            print(f"  [DRY-RUN] ID={post_id} 更新スキップ")
            success += 1
            continue

        ok = update_post_content(wp, post_id, new_content)
        if ok:
            success += 1
            print(f"  ✓ 完了")
        else:
            fail += 1

        time.sleep(1.0)

    print(f"\n=== 完了 ===")
    print(f"成功: {success} / スキップ: {skip} / 失敗: {fail}")


if __name__ == "__main__":
    main()
