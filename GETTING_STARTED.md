# 运行支架修复案例

Ubuntu 24.04、Python 3.12、Node.js 24、PrusaSlicer 2.7.2；COLMAP/CAD/FEM 依赖见 requirements.txt。

## 工程配方：视图到制造

```bash
sudo apt-get install libgl1 libglu1-mesa libglib2.0-0t64 prusa-slicer
bash scripts/bootstrap.sh
source .venv/bin/activate
export PYTHONPATH="$PWD/src"
python recipes/rebuild_bracket.py
```
示例读取 `inputs/bracket` 的 18 张视图与尺度参考，完成量测、CAD、两档网格有限元和切片。示例修复参数为厚度 7.4 mm、圆角 6 mm；新产物写入独立 `runs/example_*`。

## 多模态修复任务

在仓库外安装兼容 AGH，然后在本项目已激活的 Python 环境连接：

```bash
export AGH_SOURCE_DIR=/opt/agnes-harness
(cd "$AGH_SOURCE_DIR" && pnpm install --frozen-lockfile && pnpm --filter @agnes/cli build:local)
python scripts/connect_runtime.py
```

可先运行连接脚本并添加 `--check` 检查依赖。CLI、SDK 和 MHS 均来自这份外部安装；本项目生成的连接和运行输出由 `.gitignore` 排除。


```bash
set -a; source .env; set +a
bash start.sh --live --port 49905 --foreground
```
另一个终端：

```bash
source .venv/bin/activate
export PYTHONPATH="$PWD/src"
python scripts/run_vision_and_export.py --run-id repair_001 --case-id bracket
```
`MODEL_BASE_URL` 指向 Messages 模型服务，`REPAIRFORGE_MODEL_API_KEY` 提供访问凭据。AGH 接收图片和需求，调用原生工具完成量测、参数选择和修复。专业软件计算新的几何、强度与制造产物。

## 结构与切片检查

```bash
PYTHONPATH=src python -m pytest tests/test_design_loop.py -q
```
