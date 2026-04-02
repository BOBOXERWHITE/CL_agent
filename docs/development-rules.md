# 开发规则

## 1. 文档同步

- 所有影响本地开发、部署、依赖安装、服务启动、端口、镜像源、环境变量、第三方接入方式的配置变更，必须在同一次提交中同步更新 `README.md`。
- 如果新增了基础设施服务或外部依赖，必须同时补充对应的启动命令、停止命令、验证命令和默认端口。
- 如果变更了环境变量，必须同步更新 `.env.example`，不能只改本地私有配置。

## 2. 配置落点

- 仓库级公共配置写入版本库，例如 `docker-compose.yml`、`.env.example`、`frontend/.env.example`、`frontend/.npmrc`。
- 个人机器专属路径或账号信息不直接写死到业务代码里；如果确有必要记录，必须在文档中明确标注“仅本机环境”。
- 敏感信息不写入 `README.md`，只在 `.env.example` 中保留占位或非生产默认值。

## 3. 变更验证

- 涉及配置变更时，提交前至少验证一次对应命令可以执行，例如 `docker compose config`、`docker compose ps`、`make test`、`npm run build`。
- 文档中的命令必须以当前仓库实际可执行为准，不能保留未验证的示例命令。

## 4. 当前项目附加约定

- 当前项目的基础依赖以 `docker compose` 为准，默认服务包括 PostgreSQL、Redis、MinIO、etcd、Milvus。
- 前端依赖安装镜像源以 `frontend/.npmrc` 为准；如果后续切换 npm registry，必须同步更新 `README.md` 说明原因和结果。
