"""
indexnow_submit.py
Bing IndexNow API で全記事URLを即日インデックス登録する

IndexNow は Bing / Yandex が対応。送信から数時間でクロールされる。
Google は未対応（2026年現在）だが、Bing経由で間接的に恩恵あり。

使い方:
  python indexnow_submit.py
  python indexnow_submit.py --key YOUR_KEY  # キーを上書き

環境変数:
  SITE_URL     : https://nexgen-service.com
  INDEXNOW_KEY : IndexNow API キー（WordPress プラグイン等で取得）
"""

import os
import sys
import json
import argparse
import requests
import xmlrpc.client
import datetime

WP_URL      = os.environ.get("WP_URL", "https://nexgen-service.com")
WP_USERNAME = os.environ.get("WP_USERNAME", "nexgen")
WP_PASSWORD = os.environ.get("WP_PASSWORD", "")
SITE_URL    = os.environ.get("SITE_URL", "https://nexgen-service.com")
INDEXNOW_KEY = os.environ.get("INDEXNOW_KEY", "")  # GitHub Secret: INDEXNOW_KEY

INDEXNOW_ENDPOINT = "https://api.indexnow.org/IndexNow"
BING_ENDPOINT     = "https://www.bing.com/indexnow"


def get_published_urls() -> list:
    """WordPress XML-RPC で公開記事の URL を取得する"""
    wp = xmlrpc.client.ServerProxy(f"{WP_URL}/xmlrpc.php", allow_none=True)
    urls = []
    try:
        posts = wp.wp.getPosts(
            "1", WP_USERNAME, WP_PASSWORD,
            {"post_status": "publish", "number": 200}
        )
        for p in posts:
            link = p.get("link") or p.get("post_link") or ""
            if link:
                urls.append(link)
        print(f"  WP から {len(urls)} 件のURLを取得")
    except Exception as e:
        print(f"  ⚠️ WP取得エラー: {e}")
        # フォールバック: 既知の記事URLを直接指定
        known_ids = [6, 7, 8, 9, 10, 11, 12, 42, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90]
        for pid in known_ids:
            urls.append(f"{SITE_URL}/?p={pid}")
        print(f"  フォールバック: {len(urls)} URLを使用")
    return urls


def submit_indexnow(urls: list, key: str) -> dict:
    """IndexNow API に URL リストを送信する"""
    host = SITE_URL.replace("https://", "").replace("http://", "").rstrip("/")

    payload = {
        "host": host,
        "key": key,
        "keyLocation": f"{SITE_URL}/{key}.txt",
        "urlList": urls,
    }

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "NekoShinkaCare-IndexNow/1.0",
    }

    results = {}
    # Bing に送信（最も効果的）
    for name, endpoint in [("Bing", BING_ENDPOINT), ("IndexNow", INDEXNOW_ENDPOINT)]:
        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=30)
            results[name] = {
                "status_code": resp.status_code,
                "ok": resp.status_code in (200, 202),
                "body": resp.text[:200],
            }
            status = "✅" if resp.status_code in (200, 202) else "⚠️"
            print(f"  {status} {name}: HTTP {resp.status_code}")
            if resp.text:
                print(f"     {resp.text[:100]}")
        except Exception as e:
            results[name] = {"error": str(e), "ok": False}
            print(f"  ❌ {name}: {e}")

    return results


def generate_key_file_instruction(key: str) -> str:
    """キーファイルを WordPress ルートに置く手順を返す"""
    return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IndexNow キーファイルの設置が必要です！
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
以下の内容で「{key}.txt」というファイルを
サーバーの公開ルート（public_html / wp/）に設置してください。

ファイル名: {key}.txt
ファイルの中身（1行のみ）:
{key}

設置後の確認URL: {SITE_URL}/{key}.txt
このURLにアクセスして「{key}」と表示されればOKです。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", help="IndexNow APIキーを直接指定（省略時は環境変数 INDEXNOW_KEY）")
    parser.add_argument("--urls", nargs="+", help="送信URLを直接指定（省略時はWPから取得）")
    args = parser.parse_args()

    key = args.key or INDEXNOW_KEY
    if not key:
        print("❌ INDEXNOW_KEY が設定されていません。")
        print("   GitHub Secrets に INDEXNOW_KEY を追加するか、--key オプションで指定してください。")
        print("\n【キーの生成方法】")
        print("  1. https://www.indexnow.org/documentation を開く")
        print("  2. 任意の32文字以上の英数字文字列をキーにする")
        print("  3. そのキーを GitHub Secret: INDEXNOW_KEY に登録する")
        print("  4. サーバーに {key}.txt ファイルを設置する")
        sys.exit(1)

    print(f"[{datetime.datetime.now()}] IndexNow 送信開始")
    print(f"  キー: {key[:8]}{'*' * (len(key)-8)}")

    # URL 取得
    if args.urls:
        urls = args.urls
        print(f"  指定URL: {len(urls)} 件")
    else:
        print("  WordPress から URL を取得中...")
        urls = get_published_urls()

    if not urls:
        print("❌ 送信するURLがありません")
        sys.exit(1)

    # サイトマップURLも追加
    sitemap_urls = [f"{SITE_URL}/sitemap.xml", f"{SITE_URL}/"]
    all_urls = list(set(urls + sitemap_urls))
    print(f"  合計 {len(all_urls)} URL を送信")

    # IndexNow 送信
    results = submit_indexnow(all_urls, key)

    # レポート保存
    report = {
        "date": datetime.datetime.now().isoformat(),
        "key_prefix": key[:8],
        "url_count": len(all_urls),
        "results": results,
        "urls": all_urls[:5],  # 先頭5件のみ記録
    }
    report_file = os.path.join(os.path.dirname(__file__), "indexnow_report.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    success = sum(1 for r in results.values() if r.get("ok"))
    print(f"\n✅ 完了: {success}/{len(results)} エンドポイント成功")
    print(f"レポート保存: indexnow_report.json")

    # キーファイルの案内
    print(generate_key_file_instruction(key))


if __name__ == "__main__":
    main()
