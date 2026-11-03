# safari-cache-rescue

`safari-cache-rescue` 是一个小型、仅在本地运行的 macOS 命令行工具，用于查找 Safari WebKit 磁盘缓存中仍然存在的 HTML 文档。它针对一种特定的紧急情况而设计：最近访问过的网页已经从网络上消失，但 Safari 可能尚未淘汰其缓存响应。

本工具**不保证**能够恢复所有网页。动态应用、登录后内容、流媒体、DRM、CSS、图片、脚本和 API 响应均不在首个版本的支持范围内。

## 隐私与安全

- 只读取 Safari 的 `History.db` 和 `WebKitCache`。
- 绝不读取 Cookie、密码、自动填充、表单、SafariTabs 或无痕浏览数据。
- 绝不上传数据或发起网络请求。
- 绝不修改 Safari 数据，也不会自动打开恢复出的 HTML。
- 不创建浏览历史索引。候选项 ID 是内容的 SHA-256 哈希值。
- 导出的 HTML 可能包含脚本或远程链接，请在打开前进行检查。

Safari 数据受 macOS 保护。请为运行命令的应用（Terminal、iTerm 或 Codex）授予**完全磁盘访问权限**，然后退出并重新打开该应用：

`系统设置 > 隐私与安全性 > 完全磁盘访问权限`

## 环境要求与安装

- macOS 14 或更高版本
- Python 3.9 或更高版本

从本地检出的仓库直接运行，无需安装或配置 `PYTHONPATH`：

```bash
./safari-rescue doctor
```

如需安装 `safari-rescue` 命令：

```bash
python3 -m pip install -e .
safari-rescue doctor
```

## 使用方法

通过准确 URL 或关键词搜索：

```bash
./safari-rescue find "https://example.com/missing-page"
./safari-rescue find "workshop handbook" --since 2d
```

搜索最近的 Safari 历史记录。如果未提供时间选项，`recent` 默认搜索最近 12 小时：

```bash
./safari-rescue recent
./safari-rescue recent --since 30m
./safari-rescue recent --from 2026-08-23T09:00:00+08:00 --to 2026-08-23T18:00:00+08:00
```

`recent` 的普通文本输出会显示当前缓存 Blob 数量，以及仍存留 Blob 的最早和最新修改时间。这只是当前观测结果，不是保留期限保证；Safari 随时可能淘汰缓存。JSON 输出保持不变，只包含候选项。

默认隐藏低置信度 HTML。使用 `--all-candidates` 可将其包含在结果中。搜索命令还支持 `--limit 20` 和 `--json`。

请在检查候选列表后再执行导出：

```bash
./safari-rescue export 525191d5f7f8f87 --output recovered.html
```

工具会原样复制缓存字节，并写入 `recovered.html.recovery.json`。除非提供 `--force`，否则不会覆盖这两个文件中的任何一个。

## 置信度等级

- **high（高）**：HTML 完整，并且 canonical URL 匹配，或 HTML 标题与 Safari 历史记录标题完全一致。
- **medium（中）**：HTML 完整，并且标题有显著重合，或命中多个查询词。
- **low（低）**：HTML 与查询相关，但只有较弱证据或存在截断迹象。

Safari 缓存属于带版本号的内部实现细节。本工具会自动发现 `Version */Blobs` 目录，而不是硬编码某个版本；但未来的 Safari 版本仍可能需要工具进行适配。

## 开发

测试套件只使用合成的 History 数据库和缓存 Blob：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

请勿把真实浏览历史、缓存数据、Cookie 或恢复出的受版权保护页面添加到测试 Fixture 或问题报告中。

## 许可证

MIT
