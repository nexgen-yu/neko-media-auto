"""
expand_thin_articles.py
5000文字未満の薄い記事をClaude APIで本格的に拡充する。
- 2000語以上の高品質コンテンツに書き直す
- Amazonアフィリエイトリンクを必ず含める
- 比較表・FAQ・CTA ボタンを追加
"""

import os, sys, json, time, re
import requests
import anthropic

WP_URL = os.environ.get("WP_URL", "https://nexgen-service.com")
WP_USERNAME = os.environ.get("WP_USERNAME", "nexgen")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
AMAZON_TAG = "nexgen0b-22"

# 1回の実行で処理する最大記事数（GitHub Actionsのタイムアウト対策）
MAX_ARTICLES = int(os.environ.get("MAX_ARTICLES", "5"))
MIN_CHARS = 5000  # この文字数未満を対象とする

AMAZON_BUTTON_TEMPLATE = """<div style="text-align:center;margin:24px 0;">
  <a href="https://www.amazon.co.jp/s?k={keyword}&tag={tag}"
     style="display:inline-block;background:#FF9900;color:#fff;padding:14px 28px;
            border-radius:6px;font-weight:bold;text-decoration:none;font-size:16px;"
     target="_blank" rel="nofollow noopener">
    🛒 Amazonで{label}を見る
  </a>
</div>"""


def get_auth():
    return (WP_USERNAME, WP_APP_PASSWORD)


def get_thin_posts(min_chars=MIN_CHARS, per_page=100):
    """文字数が少ない公開記事を取得"""
    url = f"{WP_URL}/wp-json/wp/v2/posts"
    auth = get_auth()
    all_thin = []
    page = 1
    while True:
        resp = requests.get(url, params={
            "status": "publish", "per_page": per_page, "page": page,
            "_fields": "id,title,content,date", "orderby": "id", "order": "asc"
        }, auth=auth, timeout=30)
        if resp.status_code != 200:
            break
        posts = resp.json()
        if not posts:
            break
        for p in posts:
            content_len = len(p["content"]["rendered"])
            if content_len < min_chars:
                all_thin.append({
                    "id": p["id"],
                    "title": p["title"]["rendered"],
                    "content": p["content"]["rendered"],
                    "content_len": content_len,
                })
        page += 1
        if len(posts) < per_page:
            break
    # 短い順に並べて優先処理
    all_thin.sort(key=lambda x: x["content_len"])
    print(f"薄い記事数: {len(all_thin)}件 (< {min_chars}文字)")
    return all_thin


def build_expanded_content(title: str, old_content: str, client: anthropic.Anthropic) -> str:
    """Claude APIで記事を大幅拡充"""
    # タイトルからAmazonキーワードを推定
    amazon_keyword = extract_amazon_keyword(title)
    amazon_label = extract_amazon_label(title)

    prompt = f"""あなたは猫の健康に詳しいベテランライターです。
以下のタイトルの記事を、読者（シニア猫を飼う飼い主）にとって本当に役立つ
2500語以上の本格記事に書き直してください。

【タイトル】
{title}

【既存コンテンツ（参考・拡充のベースにしてください）】
{old_content[:2000]}

【必須要素（全て含めること）】
1. 読者が抱える悩み・問題の共感から始まる導入（200字以上）
2. 主要な見出し（h2）を最低5個、各見出し下に詳細本文（300字以上）
3. 商品比較表（HTMLテーブルで3〜5製品を比較、各製品にAmazonリンク付き）
   - Amazonリンク形式: https://www.amazon.co.jp/s?k=[商品キーワード]&tag={AMAZON_TAG}
4. 獣医師の視点から見た注意点セクション
5. FAQ（よくある質問と回答）を5個以上
6. まとめ（今すぐできるアクション3つ）

【書き方の注意】
- 見出し番号（1. 2. など）は使用不可
- HTMLで出力（h2, h3, p, ul, li, table, strongタグを使用）
- 専門用語には平易な説明を添える
- 具体的な数値・データを含める（例：猫の腎臓病は10歳以上の猫の約30〜40%に見られます）
- Amazonリンクは必ず1〜3箇所自然に挿入する

【Amazonリンク】必ず本文中に1回以上、以下のボタンHTMLを含めてください：
{AMAZON_BUTTON_TEMPLATE.format(keyword=amazon_keyword, tag=AMAZON_TAG, label=amazon_label)}

本文のみHTMLで出力してください（前置き・後記不要）:"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()


def extract_amazon_keyword(title: str) -> str:
    """タイトルからAmazonキーワードを生成"""
    keywords_map = {
        "フード": "猫 腎臓病 フード",
        "サプリ": "猫 腎臓 サプリメント",
        "給水器": "猫 給水器 自動",
        "アゾディル": "アゾディル 猫",
        "プロネフラ": "プロネフラ 猫",
        "リン吸着": "猫 リン吸着剤",
        "皮下輸液": "猫 皮下輸液 セット",
        "腎臓病": "猫 腎臓 サポート",
        "シニア": "シニア猫 フード",
        "ビタミン": "猫 ビタミン サプリ",
        "霊芝": "猫 サプリメント 免疫",
        "電解質": "猫 電解質 補給",
        "血液透析": "猫 腎臓 サポート",
        "AIM": "猫 腎臓 サプリメント",
        "BUN": "猫 腎臓 サポート フード",
    }
    for key, kw in keywords_map.items():
        if key in title:
            return kw
    return "猫 腎臓 ケア"


def extract_amazon_label(title: str) -> str:
    """タイトルからAmazonボタンのラベルを生成"""
    labels_map = {
        "フード": "腎臓ケアフード",
        "サプリ": "腎臓サプリ",
        "給水器": "猫用給水器",
        "アゾディル": "アゾディル",
        "プロネフラ": "プロネフラ",
        "リン吸着": "リン吸着剤",
        "皮下輸液": "輸液セット",
        "ビタミン": "猫用サプリ",
        "シニア": "シニア猫フード",
    }
    for key, label in labels_map.items():
        if key in title:
            return label
    return "関連商品"


def update_post(post_id: int, content: str) -> bool:
    """WP REST APIで記事を更新"""
    url = f"{WP_URL}/wp-json/wp/v2/posts/{post_id}"
    auth = get_auth()
    resp = requests.post(url, json={"content": content}, auth=auth, timeout=30)
    if resp.status_code == 200:
        print(f"  ✅ ID={post_id} 更新成功 ({len(content)}文字)")
        return True
    else:
        print(f"  ❌ ID={post_id} 更新失敗: {resp.status_code} {resp.text[:100]}")
        return False


def main():
    missing = []
    if not WP_APP_PASSWORD: missing.append("WP_APP_PASSWORD")
    if not CLAUDE_API_KEY: missing.append("CLAUDE_API_KEY")
    if missing:
        print(f"[ERROR] 未設定: {', '.join(missing)}")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    print("=== 薄い記事拡充スクリプト ===")
    thin_posts = get_thin_posts()

    if not thin_posts:
        print("拡充対象の記事はありません")
        return

    success = fail = 0
    for post in thin_posts[:MAX_ARTICLES]:
        pid = post["id"]
        title = post["title"]
        print(f"\n処理中 ID={pid}「{title[:40]}」({post['content_len']}文字)")

        try:
            new_content = build_expanded_content(title, post["content"], client)
            print(f"  生成完了: {len(new_content)}文字")
            if update_post(pid, new_content):
                success += 1
            else:
                fail += 1
        except Exception as e:
            print(f"  [ERROR] {e}")
            fail += 1

        time.sleep(3)  # API rate limit対策

    print(f"\n=== 完了 ===")
    print(f"成功: {success} / 失敗: {fail} / 残り: {len(thin_posts) - success - fail}件")


if __name__ == "__main__":
    main()
