"""
rewrite_daily.py
毎日1記事を競合分析してリライトし、WordPressに反映する

① Web検索で上位10記事のURLを収集
② 各記事の内容を読み込み・分析（見出し構成・文字数・独自要素・CTA位置）
③ バズ要素・差別化ポイントを抽出
④ 自記事に反映したリライト案を作成
⑤ WordPressに直接反映
"""

import os
import json
import xmlrpc.client
import anthropic
import datetime
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

# ============================================================
# 設定（GitHub Secrets から読み込む）
# ============================================================
WP_URL       = os.environ.get("WP_URL", "https://nexgen-service.com")
WP_USERNAME  = os.environ.get("WP_USERNAME", "nexgen")
WP_PASSWORD  = os.environ.get("WP_PASSWORD", "")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
AMAZON_TAG   = "nexgen0b-22"

# リライト対象記事ID（ローテーション）
TARGET_POST_IDS = [6, 7, 8, 9, 10, 11, 12, 42, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90]
REWRITE_STATE_FILE = os.path.join(os.path.dirname(__file__), "rewrite_state.json")

# ============================================================
# リライト対象ローテーション管理
# ============================================================
def get_next_target() -> int:
    if os.path.exists(REWRITE_STATE_FILE):
        with open(REWRITE_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = {"last_index": -1, "history": []}

    next_index = (state.get("last_index", -1) + 1) % len(TARGET_POST_IDS)
    state["last_index"] = next_index
    state.setdefault("history", []).append({
        "post_id": TARGET_POST_IDS[next_index],
        "date": datetime.datetime.now().isoformat()
    })

    with open(REWRITE_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    return TARGET_POST_IDS[next_index]

# ============================================================
# WordPress記事取得
# ============================================================
def get_wp_post(post_id: int) -> dict:
    wp = xmlrpc.client.ServerProxy(f"{WP_URL}/xmlrpc.php", allow_none=True)
    post = wp.wp.getPost("1", WP_USERNAME, WP_PASSWORD, post_id)
    return post

# ============================================================
# WordPress記事更新
# ============================================================
def update_wp_post(post_id: int, title: str, content: str, excerpt: str) -> bool:
    wp = xmlrpc.client.ServerProxy(f"{WP_URL}/xmlrpc.php", allow_none=True)
    post_data = {
        "post_title":   title,
        "post_content": content,
        "post_excerpt": excerpt,
        "post_status":  "publish",
    }
    result = wp.wp.editPost("1", WP_USERNAME, WP_PASSWORD, post_id, post_data)
    return bool(result)

# ============================================================
# ① Web検索で上位URLを収集
# ============================================================
def search_top_articles(keyword: str, num: int = 10) -> list:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(
                f"{keyword} 猫 腎臓病 シニア猫",
                max_results=num,
                region="jp-jp"
            ))
        urls = [r["href"] for r in results if r.get("href")]
        print(f"    検索ヒット: {len(urls)}件")
        return urls[:num]
    except Exception as e:
        print(f"    検索エラー: {e}")
        return []

# ============================================================
# ② 各記事を取得・分析
# ============================================================
def fetch_article(url: str) -> dict:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
            tag.decompose()

        headings = []
        for h in soup.find_all(["h1", "h2", "h3"]):
            text = h.get_text(strip=True)
            if text:
                headings.append(f"{h.name}: {text}")

        cta_positions = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if any(kw in href for kw in ["amazon", "rakuten", "affi", "aff", "click"]):
                all_text = soup.get_text()
                pos_text = a.get_text()
                idx = all_text.find(pos_text)
                pct = round(idx / max(len(all_text), 1) * 100)
                cta_positions.append(f"{text[:20]}（{pct}%位置）")

        body_text = soup.get_text(separator="\n", strip=True)
        char_count = len(body_text)

        return {
            "url": url,
            "headings": headings[:15],
            "cta_positions": cta_positions[:5],
            "char_count": char_count,
            "text_preview": body_text[:2000],
        }
    except Exception as e:
        return {"url": url, "error": str(e)}

# ============================================================
# ③④ Claude で競合分析＋リライト生成
# ============================================================
def analyze_and_rewrite(current_post: dict, competitors: list) -> dict:
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    competitor_text = ""
    valid_count = 0
    for i, c in enumerate(competitors, 1):
        if "error" in c:
            continue
        valid_count += 1
        competitor_text += f"""
### 競合{i}: {c['url']}
- 文字数: {c['char_count']:,}字
- 見出し構成:
{chr(10).join('  ' + h for h in c['headings'][:8])}
- CTAの位置: {', '.join(c.get('cta_positions', ['検出なし']))}
- 冒頭内容:
{c['text_preview'][:400]}
"""

    current_title   = current_post.get("post_title", "")
    current_content = str(current_post.get("post_content", ""))[:1500]

    prompt = f"""あなたはSEO専門家・コンテンツストラテジストです。
以下の「自記事」を、競合上位記事の分析に基づいてリライトしてください。

## 自記事
タイトル: {current_title}
現在の内容（冒頭）: {current_content}

## 競合上位{valid_count}記事の分析
{competitor_text}

## リライト要件
- 文字数: 1,500〜2,000字
- 見出し（h2・h3）: 4〜6個
- 比較表（HTML table）: 必ず1つ
- Amazonアフィリエイトボタン: 2〜3個
  形式: <a href="https://www.amazon.co.jp/s?k={{検索ワード}}&tag=nexgen0b-22" target="_blank" rel="noopener" style="display:inline-block;background:#ff9900;color:#fff;padding:8px 16px;border-radius:4px;text-decoration:none;font-weight:bold;">Amazonで見る</a>
- FAQ: 3問
- 「必ず獣医師にご相談ください」を医療情報に付記
- WordPress Gutenbergブロックコメント形式
- 競合にない独自ポイントを必ず含める

## 出力形式（JSONのみ）
{{
  "title": "改善後SEOタイトル（32字以内）",
  "content": "WordPress HTMLコンテンツ",
  "excerpt": "記事概要（120字以内）",
  "analysis_summary": "競合分析の要点と差別化ポイント（200字）"
}}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    return json.loads(raw)

# ============================================================
# メイン処理
# ============================================================
def main():
    start = datetime.datetime.now()
    print(f"[{start}] 競合分析リライト開始")

    post_id = get_next_target()
    print(f"  対象記事ID: {post_id}")

    print("  現在の記事を取得中...")
    current_post = get_wp_post(post_id)
    title = current_post.get("post_title", "")
    print(f"  タイトル: {title}")

    print("  ① 競合記事を検索中...")
    urls = search_top_articles(title)
    if not urls:
        print("  ⚠️ 競合記事が見つかりませんでした。スキップします。")
        return

    print(f"  ② {len(urls)}件の競合記事を分析中...")
    competitors = []
    for url in urls[:8]:
        print(f"    取得: {url[:70]}...")
        data = fetch_article(url)
        if "error" in data:
            print(f"    ⚠️ 取得失敗: {data['error'][:60]}")
        else:
            print(f"    ✅ {data['char_count']:,}字 / 見出し{len(data['headings'])}個")
        competitors.append(data)

    valid = [c for c in competitors if "error" not in c]
    print(f"  有効な競合記事: {len(valid)}件")

    if len(valid) < 2:
        print("  ⚠️ 分析に十分な競合データが取得できませんでした。スキップします。")
        return

    print("  ③④ Claude で競合分析＋リライト生成中...")
    result = analyze_and_rewrite(current_post, competitors)

    print(f"  分析サマリー: {result.get('analysis_summary', 'N/A')}")
    print(f"  新タイトル: {result.get('title', '')}")

    print("  ⑤ WordPress に反映中...")
    success = update_wp_post(
        post_id=post_id,
        title=result["title"],
        content=result["content"],
        excerpt=result["excerpt"]
    )

    if success:
        elapsed = (datetime.datetime.now() - start).seconds
        print(f"\n  ✅ リライト完了 — ID:{post_id} / {result['title']} ({elapsed}秒)")
    else:
        print(f"\n  ❌ WordPress更新に失敗しました")

    print(f"[{datetime.datetime.now()}] 完了")

if __name__ == "__main__":
    main()
