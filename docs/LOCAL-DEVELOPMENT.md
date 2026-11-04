# 本地开发

优先使用本机 Node.js 22、Python 3.12（与生产镜像一致）和浏览器。静态检查、单测、前端构建及 mock 浏览器验收不需要 Docker；真实 PostgreSQL/Redis 集成验收及完整本地应用才按需使用 Docker Desktop。

```bash
npm ci
python -m venv backend/.venv
backend/.venv/bin/pip install -i https://mirrors.tencent.com/pypi/simple -r backend/requirements-dev.txt
make dev-web           # 本机 Vite，不需要 Docker
make preflight-lite    # 本机静态检查、迁移 head、单测、前端构建
npm run test:e2e:smoke  # 临时 Vite + 浏览器，结束自动关闭
make preflight         # 追加临时 PostgreSQL/Redis 集成验收
```

从 `main` 创建 `codex/feature-*` 或 `codex/fix-*` 分支；小步提交；数据库变更通过 Alembic。提交前运行 `make preflight-lite`，发布前运行完整 `make preflight` 和对应 e2e。按改动范围选择验证集见 [测试指南](TESTING.md)。

## 临时依赖与退出清理

| 入口                     | 运行方式                                           | 结束后                              |
| ------------------------ | -------------------------------------------------- | ----------------------------------- |
| `make preflight-lite`    | 本机 Python/Node；pytest 使用临时 SQLite/fakeredis | 删除测试数据库，不创建容器          |
| `npm run test:e2e:smoke` | Playwright 自动启动 Vite，使用 mock API            | 关闭临时服务与浏览器                |
| `make migration-check`   | 临时 PostgreSQL，完整 Alembic 升级                 | 删除容器、网络与测试数据            |
| `make test-middleware`   | 临时 PostgreSQL/Redis，验证并发领取与租约恢复      | 删除容器、网络与测试数据            |
| `make dev`               | 本机 Uvicorn/Vite，仅数据依赖使用临时容器          | Ctrl-C 关闭应用和依赖，删除本次数据 |
| `make docker-build`      | 显式容器构建验收，使用本次唯一镜像标签             | 删除本次镜像标签和临时资源          |

`scripts/local_runtime.py` 统一管理生命周期。每次生成唯一 Compose 项目名，数据服务只绑定随机回环端口，数据保存在 tmpfs，不挂载旧数据库卷；正常退出、检查失败及 SIGINT/SIGTERM 均执行清理。强制断电、Docker daemon 停止或 SIGKILL 无法保证退出钩子执行，此时按日志中的 `mv-local-<批次>` 精确清理该批次，禁止全局 prune。共享基础镜像与构建缓存可复用，不属于本次测试数据。

`make dev` 默认禁用平台 Key、使用测试平台地址，不加载生产 runtime secrets，不自动创建管理员。需要完整交互时，通过受控管理员初始化流程建立临时身份；退出后数据不保留。`make stop` 仅用于停止旧版常驻 Compose 栈，保留其历史数据卷。不要把需要保留的数据放入新的临时环境。

## Docker 使用边界

本机临时 Docker 入口组合加载 `docker-compose.yml`、`docker-compose.local-build.yml` 及本次临时覆盖文件，使用国内代理和固定 digest。手动操作也必须带基础及 local-build 文件，禁止直连 docker.io。此机制要求 Compose 支持 `!override`（2.24.4 或更新版本）。服务器发布仍构建版本化镜像并使用 `scripts/deploy.sh`，不加载本机覆盖文件。

需要本地构建验证时：

```bash
make docker-build
# 代理不可用时，仅为当前命令设置 LOCAL_*_BASE_IMAGE，不修改全局 Docker 配置。
```

不要修改 Docker Desktop 全局 registry mirror，也不要删除其他项目、共享基础镜像或未知历史卷。

## 数字人资产补注册已退役

所有环境均禁止配置或恢复 `ensure_asset_avatars.py`、`sync-digital-human-assets.sh` 的 cron、launchd 或其他周期任务。人物参考直接使用 TOS 原图。发布脚本会移除遗留调度。详见 [数字人资产链路](ASSET-AVATAR.md#5)。

## 测试先行与环境隔离

非紧急变更必须先部署 `https://mv-test.epaipix.com`，连接 `https://mg-test.epaipix.com`，完成远程验收后，才能按用户明确授权将同一提交发布 `https://mv.epaipix.com`（连接 `https://mg.epaipix.com`）。默认发布目标为测试；仅正在影响正式业务的紧急 Bug 修复可例外，必须记录原因并补测试回归。服务器、Key 隔离、发布证据及紧急处理详见 [部署手册](DEPLOYMENT.md#环境对应与发布顺序强制)。本地接入平台也使用测试 Key，禁止从代码默认值推断发布目标。
