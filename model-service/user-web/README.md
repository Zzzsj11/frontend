# 模型 API 用户门户

独立 Vue 3 + TypeScript 项目，可单独构建和发布，无管理后台代码、供应商密钥或父项目运行依赖。

```bash
npm ci
npm run dev       # http://127.0.0.1:5181
npm run build
```

开发时 `/portal` 默认代理 `http://127.0.0.1:8011`；可通过 `PUBLIC_API_TARGET` 修改开发代理目标。生产镜像使用同目录 Nginx 配置代理到 `public-api:8011`，跨主机部署时修改该反代上游即可。

功能包括公开 API 文档、分模型/生成方式费率、注册登录、已绑定 Key 的额度、逐任务积分消费和积分流水。用户没有创建 Key、调整额度或计费规则的入口；上述操作由独立管理台执行。

完整约定：[PORTAL-AND-CREDITS.md](../docs/PORTAL-AND-CREDITS.md)。
