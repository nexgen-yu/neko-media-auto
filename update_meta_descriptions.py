"""
update_meta_descriptions.py
全WP記事のmeta descriptionをClaude APIで一括生成・更新する

フロー:
1. WordPress XML-RPCで全公開記事を取得
2. タイトル＋本文冒頭500文字からClaude APIでmeta description（100〜120文字）を生成
3. Yoast SEOのカスタムフィールド _yoast_wpseo_metadesc を XML-RPC で更新

使い方:
  python update_meta_descriptions.py           # 全記事
  python update_meta_descriptions.py --ids 6 7 # 指定IDのみ
"""

import os
import sys
import time
import xmlrpc.client
import anthropic
import argparse
from bs4 import BeautifulSoup

WP_URL        = os.environ.get("WP_URL", "https://nexgen-service.com")
WP_USERNAME   = os.environ.get("WP_USERNAME", "nexgen")
WP_PASSWORD   = os.environ.get("WP_PASSWORD", "")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")

XMLRPC_URL = WP_URL.rstrip("/") + "/xmlrpc.php"

def generate_meta_description(title: str, body_text: str, client: anthropic.Anthropic) -> str:
    excerpt = body_text[:600].strip()
    prompt = f"""以下のブログ記事タイトルと本文冒頭をもとに、SEO最適化されたmeta descriptionを日本語で作成してください。

【条件】
- 文字数：100〜120文字（厳守）
- 記事の主な内容・メリットを簡潔に伝える
- キーワードを自然に含める
- 読者が「読みたい」と思う訴求力のある文章
- 「。」で終わる完結した文にする
- meta descriptionのみ出力（説明や前置き不要）

【タイトル】
{title}

【本文冒頭】
{excerpt}

meta description:"""
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    desc = message.content[0].text.strip()
    if len(desc) > 120:
        desc = desc[:119] + "。"
    return desc

def get_all_posts(wp: xmlrpc.client.ServerProxy) -> list:
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

def update_meta_description(wp: xmlrpc.client.ServerProxy, post_id: int, meta_desc: str) -> bool:
    try:
        result = wp.wp.editPost(1, WP_USERNAME, WP_PASSWORD, post_id, {
            "custom_fields": [{"key": "_yoast_wpseo_metadesc", "value": meta_desc}]
        })
        return bool(result)
    except Exception as e:
        print(f"  [ERROR] post_id={post_id} 更新失敗: {e}")
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="*", type=int)
    args = parser.parse_args()
    if not WP_PASSWORD or not CLAUDE_API_KEY:
        print("[ERROR] WP_PASSWORD or CLAUDE_API_KEY not set")
        sys.exit(1)
    wp = xmlrpc.client.ServerProxy(XMLRPC_URL)
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    print("=== meta description 一括更新スクリプト ===")
    if args.ids:
        posts = []
        for pid in args.ids:
            try:
                posts.append(wp.wp.getPost(1, WP_USERNAME, WP_PASSWORD, pid))
            except Exception as e:
                print(f"  [WARN] post_id={pid}: {e}")
    else:
        posts = get_all_posts(wp)
    print(f"対象記事数: {len(posts)}")
    success = skip = fail = 0
    for post in posts:
        post_id = int(post["post_id"])
        title = post.get("post_title", "").strip()
        raw_content = post.get("post_content", "")
        soup = BeautifulSoup(raw_content, "html.parser")
        body_text = soup.get_text(separator=" ", strip=True)
        if not title or not body_text:
            skip += 1
            continue
        existing_desc = ""
        for cf in post.get("custom_fields", []):
            if cf.get("key") == "_yoast_wpseo_metadesc":
                existing_desc = cf.get("value", "").strip()
                break
        if existing_desc and len(existing_desc) >= 80:
            print(f"  [SKIP] ID={post_id} 既存あり({len(existing_desc)}文字)")
            skip += 1
            continue
        print(f"  [GEN] ID={post_id} 「{title[:30]}」")
        try:
            meta_desc = generate_meta_description(title, body_text, client)
            print(f"        → {meta_desc[:60]}... ({len(meta_desc)}文字)")
            ok = update_meta_description(wp, post_id, meta_desc)
            if ok:
                success += 1
                print("        ✓ 更新成功")
            else:
                fail += 1
        except Exception as e:
            print(f"        [ERROR] {e}")
            fail += 1
        time.sleep(1.5)
    print(f"\n=== 完了 === 成功:{success} スキップ:{skip} 失敗:{fail}")

if __name__ == "__main__":
    main()
