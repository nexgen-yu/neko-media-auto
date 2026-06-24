"""
batch_rewrite.py
全記事を一括で競合分析→高品質リライト→WordPress反映する

実行フロー（各記事ごと）:
① DuckDuckGo検索で上位10記事URLを収集
② 各記事をスクレイピング（見出し構成・文字数・CTA位置・独自要素）
③ Claude Sonnetでバズ要素・差別化ポイントを抽出
④ 競合を上回る高品質リライト案を生成
⑤ WordPress XML-RPCで直接反映

使用方法:
  python batch_rewrite.py           # 全記事リライト
  python batch_rewrite.py --ids 6 7 # 指定IDのみ
  python batch_rewrite.py --daily 3  # 今日の3記事分（ローテーション）
"""

import os
import sys
import json
import time
import argparse
import xmlrpc.client
import anthropic
import datetime
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

# ============================================================
# 設定
# ============================================================
WP_URL       = os.environ.get("WP_URL", "https://nexgen-service.com")
WP_USERNAME  = os.environ.get("WP_USERNAME", "nexgen")
WP_PASSWORD  = os.environ.get("WP_PASSWORD", "")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
AMAZON_TAG   = "nexgen0b-22"

# リライト対象（品質低い順に並べる：自動生成記事 → メイン記事）
ALL_POST_IDS = [81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 6, 7, 8, 9, 10, 11, 12, 42]
STATE_FILE   = os.path.join(os.path.dirname(__file__), "rewrite_state.json")

# ============================================================
# ローテーション管理
# ============================================================
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_index": -1, "history": []}

def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def get_daily_targets(n: int) -> list:
    """今日リライトするn件のIDを返す（ローテーション）"""
    state = load_state()
    start = (state.get("last_index", -1) + 1) % len(ALL_POST_IDS)
    targets = []
    for i in range(n):
        idx = (start + i) % len(ALL_POST_IDS)
        targets.append(ALL_POST_IDS[idx])
    state["last_index"] = (start + n - 1) % len(ALL_POST_IDS)
    state.setdefault("history", []).append({
        "date": datetime.datetime.now().isoformat(),
        "post_ids": targets
    })
    save_state(state)
    return targets

# ============================================================
# WordPress操作
# ============================================================
def get_wp_post(post_id: int) -> dict:
    wp = xmlrpc.client.ServerProxy(f"{WP_URL}/xmlrpc.php", allow_none=True)
    return wp.wp.getPost("1", WP_USERNAME, WP_PASSWORD, post_id)

def update_wp_post(post_id: int, title: str, content: str, excerpt: str) -> bool:
    wp = xmlrpc.client.ServerProxy(f"{WP_URL}/xmlrpc.php", allow_none=True)
    result = wp.wp.editPost("1", WP_USERNAME, WP_PASSWORD, post_id, {
        "post_title":   title,
        "post_content": content,
        "post_excerpt": excerpt,
        "post_status":  "publish",
    })
    return bool(result)

# ============================================================
# ① 競合URLを収集
# ============================================================
def search_competitors(keyword: str, n: int = 10) -> list:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(keyword, max_results=n, region="jp-jp"))
        urls = [r["href"] for r in results if r.get("href")]
        # 自サイトを除外
        urls = [u for u in urls if "nexgen-service.com" not in u]
        print(f"    検索: {len(urls)}件ヒット")
        return urls[:n]
    except Exception as e:
        print(f"    検索エラー: {e}")
        return []

# ============================================================
# ② 競合記事をスクレイピング・分析
# ============================================================
def scrape_article(url: str) -> dict:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # ノイズ除去
        for tag in soup(["script","style","nav","footer","header","aside","iframe","noscript"]):
            tag.decompose()

        # 見出し
        headings = [f"{h.name}: {h.get_text(strip=True)}"
                    for h in soup.find_all(["h1","h2","h3"])
                    if h.get_text(strip=True)]

        # CTA検出
        cta = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if any(k in href for k in ["amazon","rakuten","affi","affiliate","click"]):
                txt = a.get_text(strip=True)[:25]
                body = soup.get_text()
                pct  = round(body.find(a.get_text()[:10]) / max(len(body),1) * 100)
                cta.append(f"「{txt}」{pct}%位置")

        body_text  = soup.get_text(separator="\n", strip=True)
        char_count = len(body_text)

        # 独自要素の検出
        has_table  = bool(soup.find("table"))
        has_video  = bool(soup.find(["video","iframe"]))
        has_image  = len(soup.find_all("img")) > 3

        return {
            "url":         url,
            "headings":    headings[:12],
            "cta":         cta[:5],
            "char_count":  char_count,
            "has_table":   has_table,
            "has_video":   has_video,
            "has_image":   has_image,
            "preview":     body_text[:1500],
        }
    except Exception as e:
        return {"url": url, "error": str(e)}

# ============================================================
# ③④ Claude で競合分析＋高品質リライト
# ============================================================
REWRITE_PROMPT = """あなたは猫の腎臓ケア分野のSEOライティングの第一人者です。
以下の「自記事」を、競合上位記事の徹底分析に基づいて**大幅に高品質化**してください。

## 自記事（現在の内容）
タイトル: {title}
本文冒頭: {current_content}

## 競合上位{n_comp}記事の分析
{competitor_summary}

## 分析チェックリスト（内部処理として実行すること）
1. 競合が必ず触れるのに自記事が抜けているトピックを列挙
2. 競合記事の平均文字数・最長文字数を把握し、上回る計画を立てる
3. 「数字で証明」「体験談調」「専門家視点」「緊急性」のうち使えるものを選択
4. Amazon CTAを配置すべき最適タイミング（読者が購入意欲を持つ瞬間）を特定
5. 競合にない独自の差別化ポイントを1〜3個設定する

## リライト要件（必須）
- **文字数**: 2,000〜2,500字（競合最長を必ず超える）
- **タイトル**: 検索意図を完全に満たす32字以内のSEOタイトル
- **冒頭リード文**: 読者の悩みに共感し、記事を読むべき理由を示す（150字）
- **見出し構成**: h2を3〜5個、各h2の下にh3を1〜3個。**見出しテキストに番号（1. 2. など）を付けない**（TOCプラグインが自動採番するため重複になる）
- **比較表**: 必ず1〜2個（商品・方法・症状の比較）HTML tableで作成
- **Amazonボタン**: 必ず3個、以下の形式で挿入
  <a href="https://www.amazon.co.jp/s?k=【検索ワード】&tag={amazon_tag}" target="_blank" rel="noopener" style="display:inline-block;background:#ff9900;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold;font-size:15px;margin:10px 0;">🛒 Amazonで【商品名】を見る</a>
- **FAQ**: 読者がよく検索する質問を5問（Q&A形式）
- **専門家コメント調**: 「獣医師監修」「動物病院で確認済み」などの信頼性ワードを自然に入れる
- **免責事項**: 「※症状が気になる場合は必ず獣医師にご相談ください」
- **内部リンク誘導**: 「合わせて読みたい」セクションを記事末に追加
- **WordPress Gutenberg形式**: <!-- wp:heading --> 等のブロックコメントを使用
- **差別化ポイント**: 競合記事にない独自情報（具体的数値・体験談調表現・比較データ）を必ず含める

## 出力（JSONのみ・説明文なし）
{{
  "title": "リライト後タイトル",
  "content": "完全なWordPress HTMLコンテンツ（2000字以上）",
  "excerpt": "メタ概要文（120字以内）",
  "analysis": "競合との差別化ポイント・改善点のまとめ（300字）"
}}"""

def rewrite_with_claude(post: dict, competitors: list) -> dict:
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    valid = [c for c in competitors if "error" not in c]

    comp_summary = ""
    for i, c in enumerate(valid[:8], 1):
        comp_summary += f"""
### 競合{i}: {c['url']}
- 文字数: {c['char_count']:,}字 / 表: {'あり' if c.get('has_table') else 'なし'} / 画像: {'あり' if c.get('has_image') else 'なし'}
- 見出し:
{chr(10).join('  ' + h for h in c['headings'][:8])}
- CTA位置: {', '.join(c['cta']) if c['cta'] else '検出なし'}
- 本文冒頭:
{c['preview'][:500]}
"""

    prompt = REWRITE_PROMPT.format(
        title           = post.get("post_title", ""),
        current_content = str(post.get("post_content",""))[:1200],
        n_comp          = len(valid),
        competitor_summary = comp_summary,
        amazon_tag      = AMAZON_TAG,
    )

    msg = client.messages.create(
        model      = "claude-haiku-4-5-20251001",
        max_tokens = 5000,
        messages   = [{"role": "user", "content": prompt}]
    )

    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ============================================================
# 1記事をフルフローで処理
# ============================================================
def process_one(post_id: int) -> bool:
    print(f"\n{'='*60}")
    print(f"記事ID {post_id} のリライト開始")

    # 現在の記事取得
    try:
        post = get_wp_post(post_id)
    except Exception as e:
        print(f"  ❌ WP取得失敗: {e}")
        return False

    title = post.get("post_title","")
    print(f"  タイトル: {title}")

    # ① 競合検索
    print("  ① 競合を検索中...")
    urls = search_competitors(f"{title} 猫 腎臓病 シニア猫")
    if not urls:
        print("  ⚠️ 競合なし、スキップ")
        return False

    # ② スクレイピング
    print(f"  ② {len(urls)}件を取得・分析中...")
    competitors = []
    for url in urls[:8]:
        print(f"     → {url[:65]}...")
        data = scrape_article(url)
        if "error" not in data:
            print(f"       ✅ {data['char_count']:,}字 / h見出し{len(data['headings'])}個 / 表{'あり' if data['has_table'] else 'なし'}")
        else:
            print(f"       ⚠️ {data['error'][:50]}")
        competitors.append(data)
        time.sleep(0.5)  # レート制限対策

    valid = [c for c in competitors if "error" not in c]
    if len(valid) < 2:
        print("  ⚠️ 有効な競合データ不足、スキップ")
        return False

    # ③④ Claude リライト
    print(f"  ③④ Claude でリライト中（競合{len(valid)}件分析）...")
    try:
        result = rewrite_with_claude(post, competitors)
    except Exception as e:
        print(f"  ❌ Claude エラー: {e}")
        return False

    print(f"  新タイトル: {result.get('title','')}")
    content_len = len(result.get('content',''))
    print(f"  コンテンツ: {content_len:,}字")
    print(f"  分析: {result.get('analysis','')[:100]}...")

    # ⑤ WordPress反映
    print("  ⑤ WordPress に反映中...")
    try:
        ok = update_wp_post(
            post_id = post_id,
            title   = result["title"],
            content = result["content"],
            excerpt = result["excerpt"],
        )
        if ok:
            print(f"  ✅ 完了 — ID:{post_id} / {result['title']}")
            return True
        else:
            print("  ❌ WP更新失敗")
            return False
    except Exception as e:
        print(f"  ❌ WP更新エラー: {e}")
        return False

# ============================================================
# メイン
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids",   nargs="+", type=int, help="対象記事IDを指定")
    parser.add_argument("--daily", type=int,  default=0, help="今日分N記事をローテーションで処理")
    parser.add_argument("--all",   action="store_true",  help="全18記事を処理")
    args = parser.parse_args()

    if args.ids:
        targets = args.ids
        print(f"指定ID: {targets}")
    elif args.all:
        targets = ALL_POST_IDS
        print(f"全記事モード: {len(targets)}記事")
    elif args.daily > 0:
        targets = get_daily_targets(args.daily)
        print(f"今日の{args.daily}記事: {targets}")
    else:
        # デフォルト: 毎日3記事
        targets = get_daily_targets(3)
        print(f"デフォルト3記事: {targets}")

    start = datetime.datetime.now()
    print(f"\n[{start}] バッチリライト開始 — {len(targets)}記事")

    success = 0
    failed  = 0
    for post_id in targets:
        ok = process_one(post_id)
        if ok:
            success += 1
        else:
            failed += 1
        time.sleep(2)  # WPへの負荷軽減

    elapsed = (datetime.datetime.now() - start).seconds
    print(f"\n{'='*60}")
    print(f"完了: 成功{success}件 / 失敗{failed}件 / {elapsed}秒")
    print(f"[{datetime.datetime.now()}] 終了")

if __name__ == "__main__":
    main()
