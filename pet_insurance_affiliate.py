"""
ペット保険アフィリエイトリンク自動挿入スクリプト
A8.net等のSPコード（ショートコード）取得後に実行

使い方:
  1. A8.netでペット保険プログラムに参加承認後、s1コードを以下の PROGRAMS に設定
  2. python pet_insurance_affiliate.py

GitHub Secrets: WP_URL, WP_USERNAME, WP_PASSWORD
"""

import os
import re
import xmlrpc.client
from html import unescape

WP_URL      = os.environ.get("WP_URL", "https://nexgen-service.com")
WP_USERNAME = os.environ.get("WP_USERNAME", "nexgen")
WP_PASSWORD = os.environ.get("WP_PASSWORD", "")

# ─── A8.net ペット保険プログラム設定 ────────────────────────────────
# 参加承認後、A8.netの「広告リンク」ページから s1 コードを取得して設定
PROGRAMS = {
    "アニコム損保": {
        "a8_s1": os.environ.get("A8_ANICOM_S1", ""),   # 例: s00000012345001
        "display_name": "アニコム損保",
        "product": "どうぶつ健保ふぁみりぃ",
        "price_range": "月々約1,870円〜（猫・0歳の場合）",
        "coverage": "70%",
        "note": "業界最多の動物病院数・窓口清算可能",
        "url_base": "https://px.a8.net/svt/ejp",
    },
    "PS保険": {
        "a8_s1": os.environ.get("A8_PS_S1", ""),
        "display_name": "PS保険（ペット損害保険）",
        "product": "PS保険",
        "price_range": "月々約1,120円〜（猫・0歳の場合）",
        "coverage": "70%",
        "note": "ネット完結・安い保険料",
        "url_base": "https://px.a8.net/svt/ejp",
    },
    "SBI損保": {
        "a8_s1": os.environ.get("A8_SBI_S1", ""),
        "display_name": "SBI損保のペット保険",
        "product": "SBIペット保険",
        "price_range": "月々約1,110円〜（猫・0歳の場合）",
        "coverage": "70% / 90%",
        "note": "ネット申込み・シンプルプラン",
        "url_base": "https://px.a8.net/svt/ejp",
    },
    "楽天ペット保険": {
        "a8_s1": os.environ.get("A8_RAKUTEN_PET_S1", ""),
        "display_name": "楽天ペット保険",
        "product": "楽天ペット保険",
        "price_range": "月々約1,530円〜（猫・0歳の場合）",
        "coverage": "70% / 50%",
        "note": "楽天ポイント還元・窓口清算可",
        "url_base": "https://px.a8.net/svt/ejp",
    },
}

# ─── アフィリエイトリンクHTML生成 ──────────────────────────────────
def make_a8_link(s1: str, display_name: str, product: str) -> str:
    """A8.netのアフィリエイトリンクHTMLを生成"""
    if not s1:
        return ""
    # A8.netの標準リンク形式
    url = f"https://px.a8.net/svt/ejp?a8mat={s1}"
    return (
        f'<a href="{url}" rel="nofollow" target="_blank">'
        f'【公式】{display_name}「{product}」の詳細・申込みはこちら'
        f'</a>'
        f'<img border="0" width="1" height="1" src="https://www18.a8.net/0.gif?a8mat={s1}" alt="">'
    )


def make_comparison_table(programs: dict) -> str:
    """ペット保険比較表を生成"""
    rows = ""
    for key, info in programs.items():
        if not info["a8_s1"]:
            continue
        link = make_a8_link(info["a8_s1"], info["display_name"], info["product"])
        rows += f"""
        <tr>
          <td><strong>{info['display_name']}</strong></td>
          <td>{info['price_range']}</td>
          <td>{info['coverage']}</td>
          <td>{info['note']}</td>
          <td>{link}</td>
        </tr>"""

    if not rows:
        return ""

    return f"""
<h2>ペット保険比較表</h2>
<div class="pet-insurance-table" style="overflow-x:auto;">
<table border="1" style="border-collapse:collapse;width:100%;font-size:14px;">
<thead>
  <tr style="background:#f5f5f5;">
    <th>保険会社</th>
    <th>保険料目安</th>
    <th>補償割合</th>
    <th>特徴</th>
    <th>詳細・申込み</th>
  </tr>
</thead>
<tbody>{rows}
</tbody>
</table>
</div>
<p style="font-size:12px;color:#666;">※保険料は猫・0歳・月払いの目安。詳細は各社公式サイトでご確認ください。</p>
"""


def make_cta_block(programs: dict) -> str:
    """記事末尾のCTAブロックを生成"""
    blocks = []
    for key, info in programs.items():
        if not info["a8_s1"]:
            continue
        link = make_a8_link(info["a8_s1"], info["display_name"], info["product"])
        blocks.append(
            f'<div style="border:2px solid #ff6600;border-radius:8px;padding:16px;margin:12px 0;text-align:center;">'
            f'<p style="font-weight:bold;font-size:16px;color:#ff6600;">🐾 {info["display_name"]}</p>'
            f'<p>{info["note"]}</p>'
            f'<p>{link}</p>'
            f'</div>'
        )
    return "\n".join(blocks)


# ─── WP記事の取得・更新 ────────────────────────────────────────────
def get_pet_insurance_posts(client, wp_user, wp_pass) -> list:
    """ペット保険カテゴリの記事IDリストを取得"""
    posts = client.wp.getPosts(
        1, wp_user, wp_pass,
        {
            "post_type": "post",
            "post_status": "publish",
            "number": 100,
            "orderby": "date",
            "order": "DESC",
        }
    )
    results = []
    for p in posts:
        cats = [c["name"] for c in p.get("terms", {}).get("category", [])]
        if "ペット保険" in cats:
            results.append(p)
    return results


def insert_affiliate_to_post(client, wp_user, wp_pass, post: dict, comparison_html: str, cta_html: str) -> bool:
    """記事にアフィリエイトHTMLを挿入して更新"""
    pid = post["post_id"]
    title = post["post_title"]
    content = post["post_content"]

    # すでに挿入済みならスキップ
    if "pet-insurance-table" in content or "px.a8.net" in content:
        print(f"  スキップ（挿入済み）: [{pid}] {title[:40]}")
        return False

    # 比較表を記事冒頭（最初のh2の前）に挿入
    if comparison_html:
        content = re.sub(r"(<h2)", comparison_html + r"\1", content, count=1)

    # CTAブロックを記事末尾に追加
    if cta_html:
        content += "\n\n<h2>おすすめペット保険に申し込む</h2>\n" + cta_html

    result = client.wp.editPost(
        1, wp_user, wp_pass,
        pid,
        {"post_content": content}
    )

    if result:
        print(f"  ✅ 更新完了: [{pid}] {title[:40]}")
    else:
        print(f"  ❌ 更新失敗: [{pid}] {title[:40]}")
    return bool(result)


# ─── メイン ────────────────────────────────────────────────────────
def main():
    print("=== ペット保険アフィリエイトリンク挿入 ===")

    # A8.netのコードが未設定なら終了
    active = {k: v for k, v in PROGRAMS.items() if v["a8_s1"]}
    if not active:
        print("⚠️  A8.netのSPコードが未設定です。")
        print("A8.netでペット保険プログラムに参加し、以下の環境変数を設定してください:")
        for k in PROGRAMS:
            env_key = f"A8_{k.upper().replace(' ', '_').replace('（', '').replace('）', '')}_S1"
            print(f"  {env_key}=<s1コード>")
        print("\n参加推奨プログラム（A8.net検索キーワード）:")
        print("  - 「アニコム」「PS保険」「SBI損保ペット」「楽天ペット保険」")
        return

    print(f"アクティブなプログラム: {list(active.keys())}")

    # HTML生成
    comparison_html = make_comparison_table(active)
    cta_html = make_cta_block(active)

    # WP接続
    client = xmlrpc.client.ServerProxy(f"{WP_URL}/xmlrpc.php")
    posts = get_pet_insurance_posts(client, WP_USERNAME, WP_PASSWORD)
    print(f"ペット保険カテゴリ記事: {len(posts)}件")

    updated = 0
    for post in posts:
        if insert_affiliate_to_post(client, WP_USERNAME, WP_PASSWORD, post, comparison_html, cta_html):
            updated += 1

    print(f"\n完了: {updated}件更新")


if __name__ == "__main__":
    main()
