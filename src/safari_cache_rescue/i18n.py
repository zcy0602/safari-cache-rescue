"""Interactive-mode strings. Subcommand output stays English so scripts are unaffected."""

import os
from typing import Dict, Mapping, Optional


def detect_language(environ: Optional[Mapping[str, str]] = None) -> str:
    """Return ``"zh"`` or ``"en"`` from ``SAFARI_RESCUE_LANG`` or the POSIX locale variables.

    Terminal.app and iTerm2 set ``LANG`` from the macOS language and region by default.
    """
    environ = os.environ if environ is None else environ
    for name in ("SAFARI_RESCUE_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = environ.get(name)
        if value:
            return "zh" if value.casefold().startswith("zh") else "en"
    return "en"


EN: Dict[str, str] = {
    "history_ok": "Safari History",
    "history_bad": "Safari History unavailable",
    "cache_ok": "Cache: {count} entries",
    "cache_bad": "Safari cache unavailable",
    "access_help": (
        "Grant Full Disk Access to this terminal app in System Settings > Privacy & Security > "
        "Full Disk Access, then quit and reopen it."
    ),
    "menu_title": "What do you want to do?",
    "menu_recent": "Recent pages",
    "menu_search": "Search by URL or keywords",
    "menu_check": "Check access again",
    "menu_quit": "Quit",
    "search_prompt": "URL or keywords",
    "scanning": "Scanning the Safari cache…",
    "recent_title": "Recent pages · last {window}",
    "search_title": "Results for “{query}”",
    "found": "{count} found",
    "low_hidden": "{count} low-confidence hidden",
    "filter": "filter: {text}",
    "no_results": "No recoverable HTML found.",
    "no_match": "Nothing matches the filter.",
    "only_low": "Only low-confidence matches. Press tab to show them.",
    "reason_separator": ", ",
    "hint_list": "↑↓ move · ⏎ open · tab low confidence · type to filter · esc back",
    "hint_list_recent": "↑↓ move · ⏎ open · ←→ time window · tab low confidence · type to filter · esc back",
    "hint_select": "↑↓ move · ⏎ select · esc back",
    "hint_input": "⏎ confirm · esc cancel",
    "hint_preview": "↑↓ scroll · esc back",
    "action_preview": "Preview text",
    "action_export": "Export HTML…",
    "action_back": "Back",
    "export_prompt": "Save to",
    "overwrite": "{path} already exists. Replace it?",
    "yes": "Yes",
    "no": "No",
    "exported": "Exported {path}",
    "report": "Recovery report: {path}",
    "export_warning": "Not opened. Review it before opening: cached scripts may still run.",
    "export_failed": "Export failed: {error}",
    "source_error": "Cannot read Safari data: {error}",
    "preview_title": "Preview · {title}",
    "preview_gone": "This page is no longer in the cache.",
    "preview_empty": "(no readable text)",
    "untitled": "(untitled)",
    "high": "high",
    "medium": "med",
    "low": "low",
    "window_1h": "hour",
    "window_12h": "12 hours",
    "window_24h": "24 hours",
    "window_3d": "3 days",
    "window_7d": "7 days",
}

ZH: Dict[str, str] = {
    "history_ok": "Safari 历史记录",
    "history_bad": "无法读取 Safari 历史记录",
    "cache_ok": "缓存：{count} 条",
    "cache_bad": "无法读取 Safari 缓存",
    "access_help": "请为当前终端 App 开启“完全磁盘访问权限”：系统设置 > 隐私与安全性 > 完全磁盘访问权限，然后退出并重新打开终端。",
    "menu_title": "要做什么？",
    "menu_recent": "最近浏览的页面",
    "menu_search": "按网址或关键词搜索",
    "menu_check": "重新检查访问权限",
    "menu_quit": "退出",
    "search_prompt": "网址或关键词",
    "scanning": "正在扫描 Safari 缓存…",
    "recent_title": "最近浏览 · 最近 {window}",
    "search_title": "“{query}”的搜索结果",
    "found": "找到 {count} 个",
    "low_hidden": "已隐藏 {count} 个低可信度结果",
    "filter": "过滤：{text}",
    "no_results": "没有找到可恢复的 HTML。",
    "no_match": "没有符合过滤条件的结果。",
    "only_low": "只有低可信度的结果，按 tab 显示。",
    "reason_separator": "；",
    "hint_list": "↑↓ 选择 · ⏎ 打开 · tab 低可信度 · 输入文字过滤 · esc 返回",
    "hint_list_recent": "↑↓ 选择 · ⏎ 打开 · ←→ 时间范围 · tab 低可信度 · 输入文字过滤 · esc 返回",
    "hint_select": "↑↓ 选择 · ⏎ 确认 · esc 返回",
    "hint_input": "⏎ 确认 · esc 取消",
    "hint_preview": "↑↓ 滚动 · esc 返回",
    "action_preview": "预览正文",
    "action_export": "导出 HTML…",
    "action_back": "返回",
    "export_prompt": "保存到",
    "overwrite": "{path} 已存在，要替换吗？",
    "yes": "是",
    "no": "否",
    "exported": "已导出 {path}",
    "report": "恢复报告：{path}",
    "export_warning": "文件没有被打开。打开前请先检查：缓存里的脚本仍可能运行。",
    "export_failed": "导出失败：{error}",
    "source_error": "无法读取 Safari 数据：{error}",
    "preview_title": "预览 · {title}",
    "preview_gone": "这个页面已经不在缓存里了。",
    "preview_empty": "（没有可读的正文）",
    "untitled": "（无标题）",
    "high": "高",
    "medium": "中",
    "low": "低",
    "window_1h": "1 小时",
    "window_12h": "12 小时",
    "window_24h": "24 小时",
    "window_3d": "3 天",
    "window_7d": "7 天",
    "reason:canonical URL matches query": "canonical URL 与搜索的网址一致",
    "reason:cache record URL matches query": "缓存记录的网址与搜索的网址一致",
    "reason:canonical URL matches Safari history": "canonical URL 与历史记录一致",
    "reason:cache record URL matches Safari history": "缓存记录的网址与历史记录一致",
    "reason:HTML title matches Safari history": "标题与历史记录一致",
    "reason:HTML title overlaps Safari history": "标题与历史记录相近",
    "reason:query appears in HTML title": "标题包含搜索词",
    "reason:query appears in HTML": "正文包含搜索词",
    "reason:multiple query terms appear in HTML": "正文包含多个搜索词",
    "reason:HTML may be incomplete": "HTML 可能不完整",
}

class Strings:
    def __init__(self, language: str):
        self.table = ZH if language == "zh" else EN

    def __call__(self, key: str, **values: object) -> str:
        return self.table.get(key, EN.get(key, key)).format(**values)

    def reason(self, reason: str) -> str:
        return self.table.get("reason:" + reason, reason)
