# LobeHub Service Design

## Runtime

该 image 将官方 LobeHub application 与 PostgreSQL 17 打包为一个 Host Service，
用于个人浏览器聊天。s6 分别管理 database 与 application，application 在 database
ready 后启动；不引入 Redis、S3 或外部 search service。

LobeHub 通过 OpenAI-compatible endpoint 连接同 Host 的 SGLang。默认 endpoint 为
Podman bridge gateway 上的 `http://10.88.0.1:8003/v1`，部署时可以覆盖。

## Persistence

`/var/lib/codespace/lobehub` 是唯一持久化目录，保存 PostgreSQL cluster 与首次启动
生成的 LobeHub encryption/auth keys。image 只携带 database binary、extension 和
migration，不携带生成的 database cluster。首次启动使用标准 `initdb` 创建 cluster，
LobeHub 官方 launcher 幂等执行 schema migration。

这种布局允许替换 application container 而不改变数据库身份，同时避免把可变数据库
文件固化进 OCI layer。

## Scope

该最小部署支持对话、历史记录和 agent 配置。文件上传、知识库、Redis cache、Web
search 与多用户外部认证不属于此 Service；需要这些能力时应采用 LobeHub 官方
multi-container deployment。
