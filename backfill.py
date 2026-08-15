"""
一次性回填脚本：迁移DB + 翻译历史英文文章
用法: python3 backfill.py
"""

import asyncio
import httpx

import db
import translator


async def main():
    print("=== 步骤1: 迁移数据库（新增原文列）===")
    db.init_db()

    print("\n=== 步骤2: 预加载已译URL缓存 ===")
    done_urls = db.load_translated_urls()
    for u in done_urls:
        translator.mark_done(u)
    print(f"已译 URL: {len(done_urls)} 条")

    print("\n=== 步骤3: 查询待翻译文章 ===")
    pending = db.untranslated_articles()
    print(f"待翻译: {len(pending)} 篇")
    if not pending:
        print("无需翻译，全部已中文化。")
        return

    # 打印前5条样本
    print("\n样本（前5条）:")
    for a in pending[:5]:
        print(f"  [{a['id']}] {a['title'][:70]}")

    print(f"\n=== 步骤4: 开始翻译 {len(pending)} 篇（Google主+MyMemory备，6并发）===")
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        def progress(done, total):
            print(f"  翻译进度: {done}/{total}")
        count = await translator.translate_articles(pending, client=client,
                                                     on_progress=progress)
    print(f"\n翻译完成: {count} 篇")

    print("\n=== 步骤5: 写回数据库 ===")
    written = 0
    for art in pending:
        ok = db.update_translation(
            art["id"], art.get("title", ""), art.get("summary", ""),
            art.get("why_hot", ""), art.get("takeaway", ""),
            art.get("original_title"), art.get("original_summary"),
        )
        if ok:
            written += 1
    print(f"写回成功: {written} 篇")

    print("\n=== 完成 ===")
    stats = db.get_stats()
    print(f"总文章: {stats['total']}, 已翻译: {stats.get('translated', 0)}")


if __name__ == "__main__":
    asyncio.run(main())
