"""rss_gen.py - RSS 2.0 Feed 生成（web/rss.xml）。"""

import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src import config
from src.core.logger import get_logger

log = get_logger("html")

def generate_rss_feed(news_items, daily_analysis="", site_url=config.SITE_URL,
                      generated_at=None):
    """
    生成 RSS 2.0 Feed 文件（web/rss.xml），供阅读器订阅。
    """
    today = config.now_bjt()
    feed_path = os.path.join(config.BASE_DIR, "web", "rss.xml")

    rss = ET.Element("rss", version="2.0",
                     attrib={"xmlns:atom": "http://www.w3.org/2005/Atom"})
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = "AI & Agent 开发者晨报"
    ET.SubElement(channel, "link").text = site_url
    ET.SubElement(channel, "description").text = "每日 AI 领域精选新闻与深度分析"
    ET.SubElement(channel, "language").text = "zh-CN"
    ET.SubElement(channel, "lastBuildDate").text = today.strftime("%a, %d %b %Y %H:%M:%S +0800")
    atom_link = ET.SubElement(channel, "atom:link",
                              attrib={"href": f"{site_url}/web/rss.xml",
                                      "rel": "self", "type": "application/rss+xml"})

    for item in news_items:
        title = item.get("title", "")
        summary = item.get("summary", "")
        link = item.get("link", site_url)
        source = item.get("source", "")
        tags = item.get("tags") or []
        pub_iso = item.get("published_at", "")

        if not title:
            continue

        news_item = ET.SubElement(channel, "item")
        ET.SubElement(news_item, "title").text = title
        ET.SubElement(news_item, "link").text = link
        ET.SubElement(news_item, "description").text = summary
        ET.SubElement(news_item, "guid").text = link
        if source:
            ET.SubElement(news_item, "source").text = source
        # 发布时间：采集层 UTC ISO -> 北京时间 RFC822
        if pub_iso:
            try:
                dt = datetime.fromisoformat(pub_iso)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dt_bjt = dt.astimezone(ZoneInfo("Asia/Shanghai"))
                ET.SubElement(news_item, "pubDate").text = \
                    dt_bjt.strftime("%a, %d %b %Y %H:%M:%S +0800")
            except Exception:
                pass
        for tag in tags:
            if tag:
                ET.SubElement(news_item, "category").text = tag

    if daily_analysis:
        analysis_item = ET.SubElement(channel, "item")
        ET.SubElement(analysis_item, "title").text = f"今日深度分析 - {today.strftime('%Y-%m-%d')}"
        ET.SubElement(analysis_item, "link").text = site_url
        ET.SubElement(analysis_item, "description").text = daily_analysis
        ET.SubElement(analysis_item, "guid").text = f"{site_url}/daily-analysis/{today.strftime('%Y%m%d')}"

    # 格式化输出
    xml_bytes = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    xml_pretty = b'<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes.split(b'?>', 1)[-1].strip()

    with open(feed_path, "wb") as f:
        f.write(xml_pretty)

    log.info("已生成 RSS Feed (%d 条新闻)", len(news_items))
    return True
