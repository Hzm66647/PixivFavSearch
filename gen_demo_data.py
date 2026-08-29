# -*- coding: utf-8 -*-
"""生成纯占位假数据的 demo_data.json(24 条, 无任何真实收藏信息)"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
items = []
for i in range(1, 25):
    items.append({
        "id": str(900000000 + i),
        "title": "示例作品 %d" % i,
        "illustType": 0,
        "url": "https://i.pximg.net/c/250x250_80_a2/img-master/img/demo/demo.jpg",
        "tags": ["示例标签"],
        "userId": str(900000000 + i),
        "userName": "示例画师",
        "width": 1200,
        "height": 1200,
        "pageCount": (i % 4) + 1,
        "createDate": "2024-01-%02dT12:00:00+09:00" % i,
        "aiType": 0,
    })
with open(os.path.join(BASE, "data", "demo_data.json"), "w", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False, indent=1)
print("written:", len(items), "items")
