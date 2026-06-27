#!/usr/bin/env python3
"""
PDCA記事改善スクリプト
競合分析で特定した以下の要素を既存記事に追加：
1. IRISステージ分類表（クレアチニン値・SDMA値・生存中央値）
2. AIM薬最新情報セクション（2026年実用化予定）
3. 腸腎連関の言及
4. FAQセクション強化
5. 医療免責事項
"""

import os
import sys
import json
import requests
import base64
import anthropic
import re
from datetime import datetime

# 設定
WP_URL = os.environ.get("WP_URL", "")
WP_USERNAME = os.environ.get("WP_USERNAME", "")
WP_PASSWORD = os.environ.get("WP_PASSWORD", "")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", WP_PASSWORD)  # Application Password優先
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")

# 改善対象記事ID（主要記事を優先）
TARGET_POST_IDS = [6, 7, 8, 9, 10, 11, 12, 42]

# IRISステージ分類表（エビデンスベース）
IRIS_TABLE_HTML = """
<div class="iris-stage-table" style="margin: 2em 0; padding: 1.5em; background: #f8f9fa; border-radius: 8px; border-left: 4px solid #4a90d9;">
  <h3 style="color: #2c3e50; margin-top: 0;">🔬 IRISステージ分類（2023年改訂版）</h3>
  <table style="width: 100%; border-collapse: collapse; font-size: 0.9em;">
    <thead>
      <tr style="background: #4a90d9; color: white;">
        <th style="padding: 10px; text-align: center; border: 1px solid #ddd;">ステージ</th>
        <th style="padding: 10px; text-align: center; border: 1px solid #ddd;">クレアチニン（mg/dL）</th>
        <th style="padding: 10px; text-align: center; border: 1px solid #ddd;">SDMA（μg/dL）</th>
        <th style="padding: 10px; text-align: center; border: 1px solid #ddd;">生存中央値</th>
        <th style="padding: 10px; text-align: center; border: 1px solid #ddd;">状態</th>
      </tr>
    </thead>
    <tbody>
      <tr style="background: #e8f5e9;">
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd; font-weight: bold; color: #2e7d32;">Stage 1</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">&lt; 1.6</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">&lt; 18</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">3〜4年以上</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">腎機能正常〜軽度低下</td>
      </tr>
      <tr style="background: #fff9c4;">
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd; font-weight: bold; color: #f57f17;">Stage 2</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">1.6〜2.8</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">18〜25</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">約1,151日（約3.2年）</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">軽度CKD（症状少ない）</td>
      </tr>
      <tr style="background: #fff3e0;">
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd; font-weight: bold; color: #e65100;">Stage 3</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">2.9〜5.0</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">26〜38</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">約778日（約2.1年）</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">中等度CKD（症状あり）</td>
      </tr>
      <tr style="background: #ffebee;">
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd; font-weight: bold; color: #b71c1c;">Stage 4</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">&gt; 5.0</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">&gt; 38</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">約103日（約3.4ヶ月）</td>
        <td style="padding: 10px; text-align: center; border: 1px solid #ddd;">重度CKD（集中治療が必要）</td>
      </tr>
    </tbody>
  </table>
  <p style="font-size: 0.8em; color: #666; margin-top: 0.5em;">※ 参考：IRIS（International Renal Interest Society）2023年ガイドライン、WSAVA 2022年改訂</p>
</div>
"""

# AIM薬セクション
AIM_SECTION_HTML = """
<div class="aim-drug-info" style="margin: 2em 0; padding: 1.5em; background: #e8f4fd; border-radius: 8px; border-left: 4px solid #1976d2;">
  <h3 style="color: #1565c0; margin-top: 0;">💊 【2026年最新】AIM薬（猫腎臓病新薬）の現状</h3>
  <p>AIM（Apoptosis Inhibitor of Macrophage）は、東京大学の宮崎徹教授が発見したタンパク質で、猫の腎臓病（CKD）の進行を抑制する可能性が注目されています。</p>
  <ul>
    <li><strong>仕組み：</strong>AIMタンパク質が腎臓の細胞死を抑制し、回復を促進</li>
    <li><strong>猫限定の問題：</strong>猫はAIMが「IgM」に結合したまま機能しないという特殊な体質がある</li>
    <li><strong>治療薬の開発：</strong>機能するAIMを補充する注射薬・点眼薬の開発が進行中</li>
    <li><strong>実用化見込み：</strong>2026年内の承認・市販化が期待されている</li>
  </ul>
  <p style="background: #bbdefb; padding: 0.8em; border-radius: 4px; font-size: 0.9em;">
    ⚠️ <strong>注意：</strong>AIM薬はまだ市販されていません。最新情報は主治医の獣医師にご確認ください。
  </p>
</div>
"""

# 医療免責事項
DISCLAIMER_HTML = """
<div class="medical-disclaimer" style="margin-bottom: 2em; padding: 1em; background: #fff8e1; border-radius: 6px; border: 1px solid #ffcc02; font-size: 0.9em;">
  <strong>⚠️ 医療免責事項：</strong>本記事は一般的な情報提供を目的としており、獣医師による診断・治療の代替となるものではありません。猫の健康状態については、必ず資格を持つ獣医師にご相談ください。
</div>
"""

# 腸腎連関の説明テキスト
GUT_KIDNEY_NOTE = """
<div class="gut-kidney-note" style="margin: 1.5em 0; padding: 1em; background: #f3e5f5; border-radius: 6px; border-left: 3px solid #9c27b0;">
  <p style="margin: 0;"><strong>🦠 腸腎連関（Gut-Kidney Axis）とは？</strong><br>
  腸内細菌のバランスが崩れると、腸管バリアが損傷し毒素が血液に流入、腎臓へのダメージが増大することが最新研究で示されています。腎臓病の猫には食物繊維・プロバイオティクスの活用も検討しましょう。</p>
</div>
"""


def get_auth():
    """Application Password認証（Basic Auth）"""
    # Application PasswordはスペースなしでOK
    app_pw = WP_APP_PASSWORD.replace(" ", "")
    return (WP_USERNAME, app_pw)


def test_wp_connection():
    """接続テスト（Application Password認証）"""
    if not all([WP_URL, WP_USERNAME, WP_APP_PASSWORD]):
        raise ValueError("WP_URL, WP_USERNAME, WP_APP_PASSWORD が未設定")
    url = f"{WP_URL.rstrip('/')}/wp-json/wp/v2/users/me"
    resp = requests.get(url, auth=get_auth(), timeout=30)
    if resp.status_code == 200:
        print(f"✅ WordPress 接続成功 (Application Password認証)")
    else:
        raise ConnectionError(f"認証失敗: status={resp.status_code}, {resp.text[:200]}")


def get_post(post_id):
    """記事を取得（REST API + Application Password認証）"""
    url = f"{WP_URL.rstrip('/')}/wp-json/wp/v2/posts/{post_id}"
    try:
        resp = requests.get(url, auth=get_auth(), timeout=30,
                            params={"context": "edit"})
        if resp.status_code == 200:
            data = resp.json()
            return {
                "post_id": str(data["id"]),
                "post_title": data["title"]["raw"],
                "post_content": data["content"]["raw"],
                "post_status": data["status"],
            }
        else:
            print(f"  ⚠️ 記事 ID:{post_id} 取得失敗: {resp.status_code}")
            return None
    except Exception as e:
        print(f"  ⚠️ 記事 ID:{post_id} 取得失敗: {e}")
        return None


def needs_improvement(content, improvement_type):
    """既に改善済みかチェック"""
    if improvement_type == "disclaimer":
        return "medical-disclaimer" not in content
    elif improvement_type == "iris_table":
        return "iris-stage-table" not in content
    elif improvement_type == "aim":
        return "aim-drug-info" not in content and "AIM薬" not in content
    elif improvement_type == "gut_kidney":
        return "gut-kidney-note" not in content and "腸腎連関" not in content
    return True


def enhance_content_with_claude(title, content):
    """Claude APIでFAQセクションを強化・生成"""
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    prompt = f"""以下の猫健康メディア記事のタイトルと内容を見て、SEOに強い高品質なFAQセクションを5問生成してください。

タイトル: {title}

記事の既存内容（先頭1500文字）:
{content[:1500]}

要件:
1. 読者が実際に検索しそうな質問（「〜はどうすればいい？」「〜はいつから？」等）
2. 回答は具体的・数値入りで100〜150字
3. 獣医師推奨の内容に沿う（ただし「必ず獣医師に相談を」で締める）
4. HTML形式で出力（以下の形式）

出力形式（このHTMLのみ出力。他の説明文不要）:
<div class="faq-section" style="margin: 2em 0;">
  <h2 style="color: #2c3e50; border-bottom: 2px solid #4a90d9; padding-bottom: 0.5em;">よくある質問（FAQ）</h2>
  <div style="margin: 1em 0;">
    <h3 style="color: #4a90d9;">Q1. 〜〜〜？</h3>
    <p>A. 〜〜〜。必ず獣医師にご相談ください。</p>
  </div>
  ...（Q5まで）
</div>"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"  ⚠️ Claude API エラー: {e}")
        return None


def update_post_content(post_id, content):
    """記事を更新（REST API + Application Password認証）"""
    url = f"{WP_URL.rstrip('/')}/wp-json/wp/v2/posts/{post_id}"
    try:
        resp = requests.post(url, auth=get_auth(), json={"content": content}, timeout=60)
        if resp.status_code != 200:
            print(f"  ❌ 更新失敗 ({resp.status_code}): {resp.text[:200]}")
        return resp.status_code == 200
    except Exception as e:
        print(f"  ❌ 更新エラー: {e}")
        return False


def improve_post(post_id):
    """記事を改善"""
    print(f"\n📝 ID:{post_id} 処理中...")

    post = get_post(post_id)
    if not post:
        return False

    title = post.get("post_title", "")
    content = post.get("post_content", "")

    print(f"  タイトル: {title[:50]}...")

    original_content = content
    improvements = []

    # 1. 医療免責事項を先頭に追加
    if needs_improvement(content, "disclaimer"):
        content = DISCLAIMER_HTML + content
        improvements.append("免責事項")

    # 2. IRISステージ分類表を追加（腎臓病関連記事のみ）
    if needs_improvement(content, "iris_table") and ("腎臓" in title or "CKD" in title or "ステージ" in title):
        # <h2>の最初の見出しの後に挿入
        h2_match = re.search(r'</h2>', content)
        if h2_match:
            insert_pos = h2_match.end()
            content = content[:insert_pos] + "\n" + IRIS_TABLE_HTML + content[insert_pos:]
            improvements.append("IRISステージ表")

    # 3. AIM薬情報を追加（腎臓病記事のみ）
    if needs_improvement(content, "aim") and "腎臓" in title:
        # 記事の最後（</div>や終端の手前）に追加
        content = content + "\n" + AIM_SECTION_HTML
        improvements.append("AIM薬情報")

    # 4. 腸腎連関の言及を追加（腎臓病記事のみ）
    if needs_improvement(content, "gut_kidney") and "腎臓" in title:
        # AIM薬情報の前に追加
        if "aim-drug-info" in content:
            content = content.replace(
                '<div class="aim-drug-info"',
                GUT_KIDNEY_NOTE + '\n<div class="aim-drug-info"'
            )
        else:
            content = content + "\n" + GUT_KIDNEY_NOTE
        improvements.append("腸腎連関")

    # 5. FAQセクションを生成・追加（まだFAQがない場合）
    if "faq-section" not in content and CLAUDE_API_KEY:
        print(f"  🤖 Claude でFAQ生成中...")
        faq_html = enhance_content_with_claude(title, content)
        if faq_html and '<div class="faq-section"' in faq_html:
            content = content + "\n" + faq_html
            improvements.append("FAQ追加")

    if not improvements:
        print(f"  ✅ 改善不要（既に最新）")
        return True

    # WordPress に更新
    if update_post_content(post_id, content):
        print(f"  ✅ 更新完了: {', '.join(improvements)}")
        return True
    else:
        print(f"  ❌ 更新失敗")
        return False


def main():
    print("=" * 50)
    print("PDCA記事改善スクリプト 開始")
    print(f"対象記事数: {len(TARGET_POST_IDS)}")
    print("=" * 50)

    if not CLAUDE_API_KEY:
        print("⚠️ CLAUDE_API_KEY 未設定 → FAQスキップ")

    try:
        test_wp_connection()
    except Exception as e:
        print(f"❌ WordPress 接続失敗: {e}")
        sys.exit(1)

    success = 0
    fail = 0

    for post_id in TARGET_POST_IDS:
        if improve_post(post_id):
            success += 1
        else:
            fail += 1

    print("\n" + "=" * 50)
    print(f"完了: 成功 {success}件 / 失敗 {fail}件")
    print("=" * 50)

    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
