"""
batch_rewrite.py - 全記事一括高品質リライト

フロー:
① DuckDuckGo検索で競合URL収集
② 各記事スクレイピング（見出し/文字数/CTA/表の有無）
③④ Claude Haikuで競合分析+リライト生成
⑤ WordPress XML-RPCで直接反映

使い方:
  python batch_rewrite.py           # デフォルト3記事/日
  python batch_rewrite.py --all     # 全18記事
  python batch_rewrite.py --daily 5 # 今日5記事
  python batch_rewrite.py --ids 81 82 83
"""

import os, json, time, argparse, xmlrpc.client, anthropic, datetime, requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

WP_URL       = os.environ.get("WP_URL","https://nexgen-service.com")
WP_USERNAME  = os.environ.get("WP_USERNAME","nexgen")
WP_PASSWORD  = os.environ.get("WP_PASSWORD","")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY","")
AMAZON_TAG   = "nexgen0b-22"

# 品質低い順（自動生成記事 → メイン記事）
ALL_POST_IDS = [81,82,83,84,85,86,87,88,89,90, 6,7,8,9,10,11,12,42]
STATE_FILE   = os.path.join(os.path.dirname(__file__), "rewrite_state.json")

def load_state():
    return json.load(open(STATE_FILE,"r",encoding="utf-8")) if os.path.exists(STATE_FILE) else {"last_index":-1,"history":[]}

def save_state(s):
    json.dump(s, open(STATE_FILE,"w",encoding="utf-8"), ensure_ascii=False, indent=2)

def get_daily_targets(n):
    s = load_state()
    start = (s.get("last_index",-1)+1) % len(ALL_POST_IDS)
    ids = [ALL_POST_IDS[(start+i)%len(ALL_POST_IDS)] for i in range(n)]
    s["last_index"] = (start+n-1)%len(ALL_POST_IDS)
    s.setdefault("history",[]).append({"date":datetime.datetime.now().isoformat(),"ids":ids})
    save_state(s)
    return ids

def get_wp_post(pid):
    wp = xmlrpc.client.ServerProxy(f"{WP_URL}/xmlrpc.php", allow_none=True)
    return wp.wp.getPost("1", WP_USERNAME, WP_PASSWORD, pid)

def update_wp_post(pid, title, content, excerpt):
    wp = xmlrpc.client.ServerProxy(f"{WP_URL}/xmlrpc.php", allow_none=True)
    return bool(wp.wp.editPost("1",WP_USERNAME,WP_PASSWORD,pid,{
        "post_title":title,"post_content":content,"post_excerpt":excerpt,"post_status":"publish"}))

def search_competitors(kw, n=10):
    try:
        with DDGS() as d:
            results = list(d.text(kw, max_results=n, region="jp-jp"))
        urls = [r["href"] for r in results if r.get("href") and "nexgen-service.com" not in r["href"]]
        print(f"    検索: {len(urls)}件")
        return urls[:n]
    except Exception as e:
        print(f"    検索エラー: {e}"); return []

def scrape(url):
    try:
        h = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=h, timeout=12); r.raise_for_status()
        soup = BeautifulSoup(r.text,"lxml")
        for t in soup(["script","style","nav","footer","header","aside","iframe"]): t.decompose()
        heads = [f"{h.name}:{h.get_text(strip=True)}" for h in soup.find_all(["h1","h2","h3"]) if h.get_text(strip=True)]
        cta = []
        for a in soup.find_all("a",href=True):
            if any(k in a["href"] for k in ["amazon","rakuten","affi"]):
                body=soup.get_text(); pct=round(body.find(a.get_text()[:10])/max(len(body),1)*100)
                cta.append(f"{a.get_text(strip=True)[:20]}({pct}%)")
        body=soup.get_text(separator="\n",strip=True)
        return {"url":url,"headings":heads[:12],"cta":cta[:5],"chars":len(body),
                "table":bool(soup.find("table")),"preview":body[:1500]}
    except Exception as e:
        return {"url":url,"error":str(e)}

PROMPT = """あなたは猫の腎臓ケア分野のSEOライティングの第一人者です。
「自記事」を競合分析に基づいて大幅に高品質化してください。

## 自記事
タイトル: {title}
本文冒頭: {content}

## 競合{n}記事の分析
{comps}

## リライト要件（必須）
- 文字数: 2,000〜2,500字（競合最長を超える）
- h2を3〜5個、各h2の下にh3を1〜3個
- 比較表を1〜2個（HTMLテーブル）
- Amazonボタンを3個:
  <a href="https://www.amazon.co.jp/s?k=【KW】&tag=nexgen0b-22" target="_blank" rel="noopener" style="display:inline-block;background:#ff9900;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold;margin:10px 0;">🛒 Amazonで見る</a>
- FAQ 5問（Q&A形式）
- 「※症状が気になる場合は必ず獣医師にご相談ください」
- 「合わせて読みたい」内部リンクセクション
- WordPress Gutenbergブロックコメント形式
- 競合にない独自情報・具体的な数値・差別化ポイントを必ず含める
- 冒頭に読者の悩みへの共感リード文（150字）

## 出力（JSONのみ）
{{
  "title": "改善後タイトル（32字以内）",
  "content": "完全なWordPress HTML（2000字以上）",
  "excerpt": "メタ概要（120字以内）",
  "analysis": "競合との差別化ポイント（300字）"
}}"""

def rewrite(post, competitors):
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    valid = [c for c in competitors if "error" not in c]
    comp_text = ""
    for i,c in enumerate(valid[:8],1):
        comp_text += f"""
### 競合{i}: {c['url']}
- {c['chars']:,}字 / 表: {'あり' if c.get('table') else 'なし'}
- 見出し: {chr(10).join('  '+h for h in c['headings'][:8])}
- CTA: {', '.join(c['cta']) if c['cta'] else 'なし'}
- 冒頭: {c['preview'][:400]}"""

    prompt = PROMPT.format(
        title=post.get("post_title",""),
        content=str(post.get("post_content",""))[:1200],
        n=len(valid), comps=comp_text)

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=5000,
        messages=[{"role":"user","content":prompt}])

    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw=raw[4:]
    return json.loads(raw.strip())

def process(pid):
    print(f"\n{'='*55}\nID {pid}")
    try: post=get_wp_post(pid)
    except Exception as e: print(f"  WP取得失敗:{e}"); return False
    title=post.get("post_title","")
    print(f"  タイトル: {title}")
    print("  ① 競合検索...")
    urls=search_competitors(f"{title} 猫 腎臓病")
    if not urls: print("  ⚠️ 競合なし"); return False
    print(f"  ② {len(urls)}件分析中...")
    comps=[]
    for url in urls[:8]:
        print(f"    → {url[:60]}...")
        d=scrape(url)
        if "error" not in d: print(f"      ✅{d['chars']:,}字/h{len(d['headings'])}個/表{'あり' if d['table'] else 'なし'}")
        else: print(f"      ⚠️{d['error'][:40]}")
        comps.append(d); time.sleep(0.5)
    valid=[c for c in comps if "error" not in c]
    if len(valid)<2: print("  ⚠️ データ不足"); return False
    print(f"  ③④ Claude リライト（競合{len(valid)}件）...")
    try: result=rewrite(post,comps)
    except Exception as e: print(f"  ❌ Claude:{e}"); return False
    print(f"  新タイトル: {result.get('title','')} / {len(result.get('content',''))}字")
    print("  ⑤ WordPress反映...")
    try:
        ok=update_wp_post(pid,result["title"],result["content"],result["excerpt"])
        if ok: print(f"  ✅ 完了"); return True
        else: print("  ❌ 更新失敗"); return False
    except Exception as e: print(f"  ❌ {e}"); return False

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--ids",nargs="+",type=int)
    p.add_argument("--daily",type=int,default=0)
    p.add_argument("--all",action="store_true")
    args=p.parse_args()
    if args.ids: targets=args.ids
    elif args.all: targets=ALL_POST_IDS
    elif args.daily>0: targets=get_daily_targets(args.daily)
    else: targets=get_daily_targets(3)
    print(f"[{datetime.datetime.now()}] バッチリライト開始 — {targets}")
    ok=fail=0
    for pid in targets:
        if process(pid): ok+=1
        else: fail+=1
        time.sleep(2)
    print(f"\n完了: 成功{ok}件 / 失敗{fail}件")

if __name__=="__main__": main()
