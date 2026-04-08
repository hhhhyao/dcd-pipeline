# dcd_pipeline

`dcd_pipeline` 是一个用于开发、测试和维护 DCD pipeline 的仓库。

这个仓库面向通用的 pipeline 开发场景，而不是绑定某一条具体业务线。当前仓库里已经有一个可参考的示例目录是 `pipelines/wiki/`，可以作为目录组织和测试方式的参考示例。

## 仓库结构

- `pipelines/`
  统一存放可部署的 pipeline 代码。推荐按 `pipelines/<family>/<pipe_name>/` 组织，每个 pipe 保持自包含。
- `reference_repo/`
  通过 git submodule 管理的参考仓库，目前包括 `dcd` 和 `dcd-cli`。
- `skills/`
  面向 agent / Cursor / Codex 的技能文档，是自动化开发流程的事实来源。

## Pipe 目录建议

一个可部署的 pipe 通常应至少包含这些文件：

- `manifest.yaml`
- `__init__.py` 或 `main.py`
- `requirements.txt`
- `README.md`
- `tests/`

其中：

- `manifest.yaml` 定义 pipe 名称、作者、operation、输入输出字段、config、资源需求等元数据。
- 入口模块实现与 `operation` 对应的函数，例如 `map()`、`filter()`、`expand()`、`reduce()` 或 `ingest()`。
- `tests/` 应该可以在单个 pipe 目录上下文中独立运行，不依赖仓库根目录绝对路径。

## 参考仓库

首次拉取后请初始化 submodule：

```bash
git submodule update --init --recursive
```

当前参考仓库：

- `reference_repo/dcd`
- `reference_repo/dcd-cli`

开发 pipe 时，`reference_repo/dcd-cli` 是最重要的接口与约定来源。

## 配置 `.server_info`

仓库中提供了 [`.server_info.example`](./.server_info.example) 模板文件，其中保留了非敏感的主机和端口信息。

使用时请先复制：

```bash
cp .server_info.example .server_info
```

然后手动填写你自己的账号信息，例如：

- `DCD_TOKEN`
- `DCD_AUTHOR`
- `DCD_LOGIN_EMAIL`
- `DCD_LOGIN_PASSWORD`

`.server_info` 默认不进入 git，不要提交真实账号、密码或 token。

## 开发与验证

建议把每个 pipe 当作独立包来开发和验证。

### 1. 运行对应测试

```bash
pytest -q pipelines/<family>/<pipe_name>/tests
```

例如：

```bash
pytest -q pipelines/wiki/stage3_parse_html/tests
```

### 2. 使用 dcd-cli 校验 pipe

```bash
python3 -m dcd_cli.cli pipe validate pipelines/<family>/<pipe_name> --host "$DCD_HOST"
```

如果本地环境里的认证变量仍使用 `DCD_TOKEN`，而某些 `dcd-cli` 文档或命令示例使用 `DCD_SECRET`，请在当前 shell 中显式映射后再执行相关命令。

## 约定

- 仓库内统一使用 `dcd` 命名。
- active pipe 名称不再带 `_lance` 后缀；`.lance` 仅表示数据集存储格式，不属于 pipe 身份的一部分。
- `skills/` 是 agent 工作流的事实来源。

如果你是 agent / Codex / Cursor，请优先阅读 [AGENTS.md](./AGENTS.md)。
