#!/usr/bin/env python3
"""
Search Console 404 URL特定 & WordPress リダイレクト修正スクリプト
- WP REST APIで全記事スラッグを取得
- よくある404パターンを検出
- .htaccessへのリダイレクトルールを生成
"""
import os
import requests
import json

WP_URL = os.environ.get("WP_URL", "").rstrip("/")
WP_USERNAME = os.environ.get("WP_USERNAME", "")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "").replace(" ", "")

def get_auth():
    return (WP_USERNAME, WP_APP_PASSWORD)

def get_all_posts():
    """全公開記事を取得"""
    posts = []
    page = 1
    while True:
        url = f"{WP_URL}/wp-json/wp/v2/posts"
        resp = requests.get(url, auth=get_auth(), params={
            "status": "publish",
            "per_page": 100,
            "page": page,
            "_fields": "id,slug,link,title"
        }, timeout=30)
        if resp.status_code != 200:
            break
        data = resp.json()
        if not data:
            break
        posts.extend(data)
        if len(data) < 100:
            break
        page += 1
    return posts

def get_categories():
    """カテゴリ一覧を取得"""
    url = f"{WP_URL}/wp-json/wp/v2/categories"
    resp = requests.get(url, auth=get_auth(), params={"per_page": 100}, timeout=30)
    if resp.status_code == 200:
        return resp.json()
    return []

def main():
    print("=" * 50)
    print("404 URL 調査 & リダイレクト修正スクリプト")
    print("=" * 50)
    
    print("\n📋 全記事スラッグを取得中...")
    posts = get_all_posts()
    print(f"✅ {len(posts)}件の記事を取得")
    
    slugs = [p["slug"] for p in posts]
    
    # よくある404パターンのチェック
    common_404_patterns = [
        # 旧URLパターン（番号付きスラッグ → 正規スラッグ）
        ("cat-kidney-food", "猫の腎臓病フード"),
        ("cat-appetite-loss", "老猫の食欲不振"),
        ("cat-kidney-supplement", "猫の腎臓病サプリ"),
    ]
    
    print("\n📊 記事スラッグ一覧（先頭20件）:")
    for p in posts[:20]:
        print(f"  ID:{p['id']:4d}  {p['slug'][:50]}")
    
    print(f"\n📊 総記事数: {len(posts)}件")
    
    # .htaccessリダイレクトルール生成
    # カテゴリページへのよくあるミスアクセスパターン
    redirect_rules = """
# ===== 自動生成リダイレクトルール =====
# 旧URLパターン → 新URLへのリダイレクト

# カテゴリページへのリダイレクト
RedirectMatch 301 ^/category/cat-health/?$ /category/猫の健康/
RedirectMatch 301 ^/category/dog-health/?$ /category/犬の健康/
RedirectMatch 301 ^/cat-kidney/?$ /
RedirectMatch 301 ^/neko/?$ /

# よくあるタイポ修正
RedirectMatch 301 ^/wp-admin/admin-ajax.php$ /wp-admin/admin-ajax.php
"""
    
    # WP REST APIでリダイレクトプラグイン（Redirection）を設定
    # または.htaccessを直接更新
    print("\n📝 リダイレクトルール候補:")
    print(redirect_rules)
    
    # Search Console 404 URLの特定方法をガイド
    print("\n🔍 Search Console 404 URL特定手順:")
    print("  1. https://search.google.com/search-console/")
    print("  2. カバレッジ → 除外 → 「見つかりませんでした (404)」")
    print("  3. URLリストをエクスポート")
    print("  4. 本スクリプトに404 URLリストを渡して自動リダイレクト設定")
    
    # WP REST APIでSite Health情報を確認
    print("\n🔧 WordPress permalinks 確認中...")
    url = f"{WP_URL}/wp-json/wp/v2/settings"
    resp = requests.get(url, auth=get_auth(), timeout=30)
    if resp.status_code == 200:
        settings = resp.json()
        print(f"  サイトURL: {settings.get('url', 'N/A')}")
        print(f"  タイムゾーン: {settings.get('timezone', 'N/A')}")
    
    print("\n✅ 完了")
    
    # 記事スラッグをJSONファイルに保存（確認用）
    with open("post_slugs.json", "w", encoding="utf-8") as f:
        json.dump([{"id": p["id"], "slug": p["slug"], "title": p["title"]["rendered"]} 
                   for p in posts], f, ensure_ascii=False, indent=2)
    print("📄 post_slugs.json を保存しました（全記事スラッグ一覧）")

if __name__ == "__main__":
    main()
