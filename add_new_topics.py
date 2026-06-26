#!/usr/bin/env python3
"""一回限り：競合分析で特定した高優先度トピック10件をtopics.jsonの先頭に追加"""
import json, os

TOPICS_FILE = "topics.json"

NEW_TOPICS = [
    {"title": "猫の腸腎連関とは｜腸内環境が腎臓に与える影響とプロバイオティクスの効果", "keywords": "猫 腸腎連関 腸内環境 腎臓", "posted": False},
    {"title": "猫の腎臓病と歯周病の関係｜口腔ケアが腎機能低下を防ぐ理由と対策", "keywords": "猫 腎臓病 歯周病 口腔ケア", "posted": False},
    {"title": "猫の腎臓病ステージ別生存期間｜IRISステージ1〜4の余命と治療方針の完全ガイド", "keywords": "猫 腎臓病 ステージ 生存期間 余命", "posted": False},
    {"title": "猫の腎臓病予防に最適な給水器ランキング5選｜循環式フィルター付きを徹底比較", "keywords": "猫 給水器 腎臓病 予防 フィルター", "posted": False},
    {"title": "猫の皮下点滴を自宅でするやり方｜道具・頻度・コツ・注意点を獣医師が解説", "keywords": "猫 皮下点滴 自宅 やり方", "posted": False},
    {"title": "猫の腎臓病とリン吸着剤の選び方｜種類・効果・おすすめ商品を比較解説", "keywords": "猫 腎臓病 リン吸着剤 選び方", "posted": False},
    {"title": "猫の腎臓病で貧血になる仕組みと治療法｜エリスロポエチン不足の対処", "keywords": "猫 腎臓病 貧血 エリスロポエチン", "posted": False},
    {"title": "猫の腎臓病と高血圧の関係｜血圧管理・降圧剤・日常ケアの完全ガイド", "keywords": "猫 腎臓病 高血圧 降圧剤", "posted": False},
    {"title": "猫の腎臓病ステージ2の生存期間と治療｜QOLを維持する実践ガイド", "keywords": "猫 腎臓病 ステージ2 生存期間 治療", "posted": False},
    {"title": "猫の腎臓病に効果的な漢方薬とサプリ｜コルディ・ルナシン・ネフガード比較", "keywords": "猫 腎臓病 漢方 サプリ コルディ", "posted": False},
]

with open(TOPICS_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

topics = data["topics"]
existing = {t["title"] for t in topics}
added = 0
for nt in reversed(NEW_TOPICS):
    if nt["title"] not in existing:
        topics.insert(0, nt)
        added += 1

data["meta"]["total"] = len(topics)
with open(TOPICS_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"追加: {added}件 → 総数: {len(topics)}件")
