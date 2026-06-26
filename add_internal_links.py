"""
add_internal_links.py
WordPress記事間に内部リンクを自動追加する

フロー:
1. 全公開記事のタイトル・本文・URLを取得
2. 各記事の本文内キーワードに対して関連記事を検索
3. 「合わせて読みたい」ブロックを記事末尾に挿入
4. XML-RPCで記事を更新

使い方:
  python add_internal_links.py           # 全記事
  python add_internal_links.py --ids 6 7 # 指定IDのみ
  python add_internal_links.py --dry-run # 確認のみ（更新しない）
"""

import os
import sys
import re
import time
import xmlrpc.client
import argparse
from bs4 import BeautifulSoup

# ============================================================
# 設定
# ============================================================
WP_URL      = os.environ.get("WP_URL", "https://nexgen-service.com")
WP_USERNAME = os.environ.get("WP_USERNAME", "nexgen")
WP_PASSWORD = os.environ.get("WP_PASSWORD", "")
XMLRPC_URL  = WP_URL.rstrip("/") + "/xmlrpc.php"

# 1記事あたりの内部リンク最大数
MAX_LINKS_PER_POST = 3

# 「合わせて読みたい」ブロックのテンプレート
RELATED_BLOCK_TEMPLATE = """
<!-- wp:group {"className":"related-posts-box"} -->
<div class="wp-block-group related-posts-box">
<!-- wp:heading {"level":3} -->
<h3>合わせて読みたい</h3>
<!-- /wp:heading -->
<!-- wp:list -->
<ul>{list_items}
</ul>
<!-- /wp:list -->
</div>
<!-- /wp:group -->
"""

RELATED_ITEM_TEMPLATE = '\n<li><a href="{url}">{title}</a></li>'

# ============================================================
# 関連度スコアリング：タイトル・本文キーワードの一致数
# ============================================================
def compute_relevance(source_title: str, source_text: str, target_title: str, target_text: str) -> int:
    """ソース記事とターゲット記事の関連度スコアを計算"""
    def extract_keywords(text: str) -> set:
        tokens = re.findall(r'[ぁ-んァ-ン一-龥]{2,}', text)
        return set(t for t in tokens if len(t) >= 2)

    src_kws = extract_keywords(source_title + " " + source_text[:500])
    tgt_kws = extract_keywords(target_title + " " + target_text[:500])

    return len(src_kws & tgt_kws)


# ============================================================
# XML-RPC操作
# ============================================================
def get_all_posts(wp: xmlrpc.client.ServerProxy) -> list:
    """全公開記事を取得"""
    posts = []
    offset = 0
    per_page = 50
    while True:
        batch = wp.wp.getPosts(1, WP_USERNAME, WP_PASSWORD, {
            "post_status": "publish",
            "number": per_page,
            "offset": offset,
            "post_type": "post",
        })
        if not batch:
            break
        posts.extend(batch)
        if len(batch) < per_page:
            break
        offset += per_page
    return posts


def already_has_related_block(content: str) -> bool:
    """記事に既に「合わせて読みたい」ブロックがあるか確認"""
    return "related-posts-box" in content or "合わせて読みたい" in content


def build_related_block(related_posts: list) -> str:
    """関連記事ブロックHTMLを生成"""
    items = ""
    for post in related_posts:
        url   = post.get("link", "")
        title = post.get("post_title", "")
        items += RELATED_ITEM_TEMPLATE.format(url=url, title=title)
    return RELATED_BLOCK_TEMPLATE.format(list_items=items)


def append_related_links(wp: xmlrpc.client.ServerProxy, post_id: int, content: str, related_block: str, dry_run: bool) -> bool:
    """記事末尾に内部リンクブロックを追加"""
    new_content = content.rstrip() + "\n" + related_block
    if dry_run:
        print(f"    [DRY-RUN] ID={post_id} 更新スキップ")
        return True
    try:
        result = wp.wp.editPost(1, WP_USERNAME, WP_PASSWORD, post_id, {
            "post_content": new_content,
        })
        return bool(result)
    except Exception as e:
        print(f"    [ERROR] ID={post_id} 更新失敗: {e}")
        return False


# ============================================================
# メイン
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids",     nargs="*", type=int, help="対象post IDを指定")
    parser.add_argument("--dry-run", action="store_true", help="更新せずに確認のみ")
    args = parser.parse_args()

    if not WP_PASSWORD:
        print("[ERROR] WP_PASSWORD が未設定です")
        sys.exit(1)

    wp = xmlrpc.client.ServerProxy(XMLRPC_URL)

    print("=== 内部リンク自動追加スクリプト ===")
    print(f"対象サイト: {WP_URL}")

    print("全公開記事を取得中...")
    all_posts = get_all_posts(wp)
    print(f"総記事数: {len(all_posts)}")

    if args.ids:
        target_posts = [p for p in all_posts if int(p["post_id"]) in args.ids]
    else:
        target_posts = all_posts

    success = skip = fail = 0

    for post in target_posts:
        post_id   = int(post["post_id"])
        title     = post.get("post_title", "").strip()
        content   = post.get("post_content", "")

        soup      = BeautifulSoup(content, "html.parser")
        body_text = soup.get_text(separator=" ", strip=True)

        print(f"\n処理中 ID={post_id} 「{title[:30]}」")

        if already_has_related_block(content):
            print(f"  [SKIP] 既に「合わせて読みたい」ブロックあり")
            skip += 1
            continue

        scored = []
        for candidate in all_posts:
            cid = int(candidate["post_id"])
            if cid == post_id:
                continue
            c_title   = candidate.get("post_title", "")
            c_content = candidate.get("post_content", "")
            c_soup    = BeautifulSoup(c_content, "html.parser")
            c_text    = c_soup.get_text(separator=" ", strip=True)
            score     = compute_relevance(title, body_text, c_title, c_text)
            if score > 0:
                scored.append((score, candidate))

        scored.sort(key=lambda x: x[0], reverse=True)
        related = [p for _, p in scored[:MAX_LINKS_PER_POST]]

        if not related:
            print(f"  [SKIP] 関連記事なし")
            skip += 1
            continue

        print(f"  関連記事 {len(related)}件:")
        for _, rp in scored[:MAX_LINKS_PER_POST]:
            print(f"    → ID={rp['post_id']} 「{rp['post_title'][:30]}」")

        block = build_related_block(related)
        ok = append_related_links(wp, post_id, content, block, args.dry_run)

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
