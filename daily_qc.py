"""
daily_qc.py
毎日全記事をスキャンして品質問題を検出・自動修正する

チェック項目:
① 番号付き見出し（「1. タイトル」形式）→ 番号を除去
② 文字数不足（1500字未満）→ リライトキューに追加
③ Amazonボタンなし → 冒頭に挿入
④ 画像なし → Unsplash/Pixabayから猫画像URLを設定
"""

import os
import re
import json
import xmlrpc.client
import datetime

WP_URL      = os.environ.get("WP_URL", "https://nexgen-service.com")
WP_USERNAME = os.environ.get("WP_USERNAME", "nexgen")
WP_PASSWORD = os.environ.get("WP_PASSWORD", "")
AMAZON_TAG  = "nexgen0b-22"

ALL_POST_IDS = [6, 7, 8, 9, 10, 11, 12, 42, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90]

FALLBACK_IMAGES = [
    ("https://cdn.pixabay.com/photo/2017/02/20/18/03/cat-2083492_1280.jpg", "シニア猫"),
    ("https://cdn.pixabay.com/photo/2016/01/20/11/14/cat-1151519_1280.jpg", "猫の健康ケア"),
    ("https://cdn.pixabay.com/photo/2015/11/16/14/43/cat-1045782_1280.jpg", "猫 腎臓ケア"),
    ("https://cdn.pixabay.com/photo/2021/10/19/10/56/cat-6723256_1280.jpg", "老猫"),
    ("https://cdn.pixabay.com/photo/2017/07/25/01/22/cat-2536662_1280.jpg", "猫 健康"),
]

QC_REPORT_FILE = os.path.join(os.path.dirname(__file__), "qc_report.json")


def get_wp():
    return xmlrpc.client.ServerProxy(f"{WP_URL}/xmlrpc.php", allow_none=True)


def get_all_posts() -> list:
    wp = get_wp()
    posts = []
    for pid in ALL_POST_IDS:
        try:
            p = wp.wp.getPost("1", WP_USERNAME, WP_PASSWORD, pid)
            posts.append(p)
        except Exception as e:
            print(f"  ID{pid} 取得失敗: {e}")
    return posts


def update_post(post_id: int, content: str = None):
    wp = get_wp()
    data = {"post_status": "publish"}
    if content is not None:
        data["post_content"] = content
    return wp.wp.editPost("1", WP_USERNAME, WP_PASSWORD, post_id, data)


def fix_numbered_headings(content: str):
    pattern = r'(<h[23][^>]*>)\s*[\d１２３４５６７８９０]+[．\.\s。]+\s*'
    fixed = re.sub(pattern, r'\1', content)
    return fixed, fixed != content


def check_amazon_buttons(content: str) -> int:
    return len(re.findall(r'amazon\.co\.jp', content, re.IGNORECASE))


def add_amazon_button_top(content: str, post_title: str) -> str:
    keyword = post_title.replace("【", "").replace("】", "").split("｜")[0][:20]
    btn = (
        f'<!-- wp:html -->\n'
        f'<p style="text-align:center;margin:20px 0;">'
        f'<a href="https://www.amazon.co.jp/s?k={keyword}+猫+腎臓&tag={AMAZON_TAG}" '
        f'target="_blank" rel="noopener" '
        f'style="display:inline-block;background:#ff9900;color:#fff;padding:12px 24px;'
        f'border-radius:6px;text-decoration:none;font-weight:bold;font-size:16px;">'
        f'🛒 Amazonで関連商品を見る</a></p>\n<!-- /wp:html -->\n\n'
    )
    if "<!-- wp:paragraph -->" in content:
        return content.replace("<!-- wp:paragraph -->", btn + "<!-- wp:paragraph -->", 1)
    return btn + content


def check_has_image(content: str) -> bool:
    return bool(re.search(r'<img[^>]+>', content, re.IGNORECASE))


def add_featured_image_html(content: str, image_url: str, alt: str) -> str:
    img_block = (
        f'<!-- wp:image {{"align":"center"}} -->\n'
        f'<figure class="wp-block-image aligncenter">'
        f'<img src="{image_url}" alt="{alt}" style="max-width:100%;height:auto;border-radius:8px;" />'
        f'</figure>\n<!-- /wp:image -->\n\n'
    )
    return img_block + content


def count_text(content: str) -> int:
    text = re.sub(r'<[^>]+>', '', content)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    return len(text.strip())


def main():
    start = datetime.datetime.now()
    print(f"[{start}] 品質チェック開始 — {len(ALL_POST_IDS)}記事")

    report = {
        "date": start.isoformat(),
        "posts": [],
        "summary": {"checked": 0, "fixed": 0, "needs_rewrite": []}
    }

    posts = get_all_posts()
    img_cycle = 0

    for post in posts:
        post_id    = int(post.get("post_id", 0))
        title      = post.get("post_title", "")
        content    = str(post.get("post_content", ""))
        issues     = []
        fixes      = []
        new_content = content

        print(f"\n--- ID:{post_id} {title[:40]} ---")

        fixed_content, heading_changed = fix_numbered_headings(new_content)
        if heading_changed:
            new_content = fixed_content
            issues.append("番号付き見出し")
            fixes.append("見出し番号を除去")
            print(f"  ✅ 見出し番号修正")

        btn_count = check_amazon_buttons(new_content)
        print(f"  Amazonボタン: {btn_count}個")
        if btn_count == 0:
            new_content = add_amazon_button_top(new_content, title)
            issues.append("Amazonボタンなし")
            fixes.append("冒頭にAmazonボタン追加")
            print(f"  ✅ Amazonボタン追加")

        has_img = check_has_image(new_content)
        print(f"  画像: {'あり' if has_img else 'なし'}")
        if not has_img:
            img_url, img_alt = FALLBACK_IMAGES[img_cycle % len(FALLBACK_IMAGES)]
            img_cycle += 1
            new_content = add_featured_image_html(new_content, img_url, img_alt)
            issues.append("画像なし")
            fixes.append(f"画像追加: {img_alt}")
            print(f"  ✅ 画像追加: {img_alt}")

        char_count = count_text(new_content)
        print(f"  文字数: {char_count:,}字")
        if char_count < 1500:
            issues.append(f"文字数不足({char_count}字)")
            report["summary"]["needs_rewrite"].append(post_id)
            print(f"  ⚠️ 文字数不足 → リライト要")

        if new_content != content:
            try:
                ok = update_post(post_id, content=new_content)
                status = "更新済み" if ok else "更新失敗"
                print(f"  📝 WP更新: {status}")
                report["summary"]["fixed"] += 1
            except Exception as e:
                status = f"エラー: {e}"
                print(f"  ❌ WP更新エラー: {e}")
        else:
            status = "変更なし"
            print(f"  ✓ 問題なし")

        report["posts"].append({
            "post_id": post_id,
            "title": title,
            "issues": issues,
            "fixes": fixes,
            "char_count": char_count,
            "status": status,
        })
        report["summary"]["checked"] += 1

    with open(QC_REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    elapsed = (datetime.datetime.now() - start).seconds
    print(f"\n{'='*60}")
    print(f"完了: {report['summary']['checked']}記事 / {report['summary']['fixed']}件修正")
    print(f"リライト要: {report['summary']['needs_rewrite']}")
    print(f"所要時間: {elapsed}秒")


if __name__ == "__main__":
    main()
