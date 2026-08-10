# 发布与环境

Local、Staging、Production 使用同一镜像，不同数据库、Redis、TOS 前缀和 Secret。镜像使用不可变标签 `git-<full-sha>`，存放腾讯云 TCR。

GitHub Secrets：`TCR_NAMESPACE`、`TCR_USERNAME`、`TCR_PASSWORD`、`DEPLOY_SSH_KEY`、`DEPLOY_HOST`、`DEPLOY_USER`、`DEPLOY_PATH`、`PUBLIC_URL`、`E2E_USERNAME`、`E2E_PASSWORD`。

发布：PR 通过 CI；合并 main 后 images 工作流构建镜像；先手动运行 Deploy workflow 选择 staging；远程测试通过后用同一镜像标签发布 production。服务器 `.env.production` 至少设置 `REGISTRY`、`JWT_SECRET` 和供应商/TOS 配置。

没有 TCR 时，可在生产服务器从干净且已推送的 Git 提交构建带完整 SHA 的本地不可变镜像。将 `.env.production` 中 `REGISTRY=mvagent-local`，然后执行：

```bash
git fetch origin main
git merge --ff-only origin/main
chmod +x scripts/deploy-local-images.sh
DEPLOY_ENV=production ./scripts/deploy-local-images.sh
```

脚本拒绝脏工作区，镜像标签固定为 `git-<full-sha>`，构建成功后仍通过 `scripts/deploy.sh` 完成健康检查和版本记录。该方式不依赖远程镜像仓库，但服务器需要保留足够的 Docker 构建磁盘空间；后续恢复 TCR 时无需改业务编排。

服务器将 `.env.deploy.example` 复制为 `.env.staging` 或 `.env.production` 并替换所有占位值。手动命令：`DEPLOY_ENV=production ./scripts/deploy.sh git-<sha>`。脚本拉取镜像、启动服务、等待健康，并记录当前及上一版本。生产 PostgreSQL/Redis 不映射公网端口。

若使用 `backend/.provider_config.py` 中的统一供应商 `AIGC_TOKEN`，聊天地址和默认文本模型也必须由该配置组统一决定；不要在生产 `.env` 中保留指向其他厂商的旧 `LLM_BASE_URL`、`LLM_API_KEY` 或 `LLM_MODEL`。发布后可在容器内仅打印地址与模型（不得打印 Token）核对运行时配置。

首次部署后执行 `scripts/install-maintenance-cron.sh`，安装每 5 分钟健康检查和每日 03:15 数据库备份；Cron 日志写入项目 `logs/`。本地备份仍需按 `BACKUP-RESTORE.md` 同步到独立对象存储。
