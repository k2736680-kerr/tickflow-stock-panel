# Tickflow Stock Panel · Agent 持久记忆

> GitHub：`k2736680-kerr/tickflow-stock-panel`  
> 工作副本：`~/AutoTestTools/Projects/测试乱七八糟/tickflow-stock-panel`（Windows 旧：`D:\AutoTestTools\Projects\测试乱七八糟\tickflow-stock-panel`）

## 是什么

A 股选股/回测/复盘面板：FastAPI 后端 + 前端，本地 `data/` 存 parquet、k线、job、回测矩阵缓存。

## 本机运行

以 [`本机交接.md`](本机交接.md) 为准（启动命令、端口、今日名单流程）。Mac 迁移时把 `.env` 放到 `~/AutoTestTools/Secrets/tickflow.env` 再 source，勿提交。

---

# AI 开发入口

修改、调试或审查本仓库前，必须完整阅读并遵循根目录的 [`CONTRIBUTING.md`](CONTRIBUTING.md)。其中定义了项目架构、数据契约、数据源插件化、缓存与性能要求、测试矩阵以及 PR 复审和合并标准。

本机怎么启动、今日名单怎么买、复盘账本、以及**不要自动改 E1 / 不要本机常驻 / 不要提交 .env 和 data/**，以 [`本机交接.md`](本机交接.md) 为准。新对话没有聊天记录时，先读那份再动手。

涉及代码二次开发、前端插槽、后端可替换策略、扩展注册或上游升级兼容时，还必须阅读 [`docs/secondary-development.md`](docs/secondary-development.md)。该文档区分当前已实现能力与目标扩展契约；不得根据设计示例虚构尚不存在的 API。

同时遵守以下规则：

- 先理解调用链和现有测试，再进行修改。
- 保持实现简单、改动范围最小，不处理无关问题。
- 不覆盖工作区已有修改，不虚构测试或审查结果。
- 以实际验证结果作为完成标准。
- 不声称 90% 明天上涨，不自动下单，不根据几天实盘自动改选股条件。
