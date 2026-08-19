# XHS Pipeline — 小红书内容生成管线与工具

小红书账号「宅有宅的道理」的**内容生成管线 + 工具资产**(与内容仓库 `xhs-content`、语料仓库 `xhs-corpus` 分离)。

## 目录结构

```
xhs-pipeline/
├── workflows/        # n8n workflow JSON 导出(各版本)
│   ├── xhs-mvp2-9pics.json       # MVP-2 9图版
│   ├── xhs-mvp3-v2/v2.1.json     # MVP-3
│   ├── xhs-mvp4-v3.0.json        # MVP-4 v3.0
│   ├── xhs-hot-mcp-v1/v12/v13    # XHS-Hot MCP 管线 v1/v1.2/v1.3
│   ├── xhs-wf1-import*.json      # WF1 导入
│   └── xhs-wf3-feedback.json     # WF3 反馈
├── scene_plans/      # 场景方案配置(scene_plan,JSON 驱动配图)
│   └── scene_plan_xiaomi_smart.json   # 小米全屋智能 7 图
├── scripts/          # 辅助脚本
│   ├── cover_gen.py       # 封面生成(v4: 单图/双封面)
│   ├── cover_server.py    # 封面 HTTP 服务(:8765)
│   └── xhs-batch-runner.py# 批量测试脚本
└── baoyu-cards/      # baoyu 风格 HTML 卡片模板(headless Chrome 渲染)
    ├── cover-pop.html     # hype/pop 封面
    ├── cover-poster.html  # screen-print/poster 封面
    ├── cost.html          # knowledge-card 成本/知识卡(3列)
    ├── compare.html       # versus/bold 对比卡
    └── prereq.html        # warning/bold 前提/避坑卡
```

## 关键要点

- **管线主机**: mini-ai-svr `192.168.1.60`(n8n :5678, hauhau :8080, Comfy :8189, cover :8765)
- **MCP 数据源**: XHS-Downloader MCP,Mac mini `192.168.1.41:5556`(见 `pop4ever/xhs-corpus` 关联)
- **scene_plan 驱动**: 配图内容由 scene_plan JSON 配置,不靠模型脑补
- **文字进图**: 中文标注/卡片文字用 PIL 或 HTML 渲染,100% 准确无乱码
- **baoyu-cards 渲染**: macOS `Google Chrome --headless=new --screenshot`,带时间戳 query 防缓存
- **坑 35**: 多卡片布局用 `grid`(禁 `flex:1`,否则 padding 失效卡片贴边);布局验证用 Python 像素扫描,别信 vision 百分比

## 相关仓库

- `pop4ever/xhs-content` — 笔记产出内容(按系列分文件夹)
- `pop4ever/xhs-corpus` — 语料/数据(seed_notes, hot_notes, scores 等)

## 导入 n8n

```bash
# 在 mini-ai-svr(.60) 上,用 n8n CLI 导入(workflow JSON 需顶层含 id + webhookId)
n8n import:workflow --input=workflows/xhs-mvp4-v3.0.json
n8n publish:workflow --id=<id>
systemctl --user restart n8n
```
