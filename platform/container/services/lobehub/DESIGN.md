# LobeHub Service Design

## Runtime

该 image 将官方 LobeHub application 与 PostgreSQL 17 打包为一个 Host Service，
用于个人浏览器聊天。s6 管理 database、application 与 automatic authentication
proxy；application 在 database ready 后启动，proxy 在 application ready 后对外监听
`3210`。不引入 Redis、S3 或外部 search service。

LobeHub 通过 OpenAI-compatible endpoint 连接同 Host 的 SGLang。默认 endpoint 为
Podman bridge gateway 上的 `http://10.88.0.1:8003/v1`，部署时可以覆盖。

## Authentication

LobeHub application 只监听容器 loopback `3211`。proxy 首次启动时通过 Better Auth
官方 API 创建固定本地用户，密码生成后持久化；后续启动使用该凭据签发 session。proxy
覆盖每个转发请求中的 Better Auth cookie，因此所有能够访问 Host loopback `3210` 的
客户端共享该用户身份。proxy 同时通过 LobeHub user API 完成 onboarding，客户端不经过
注册、登录或 onboarding 页面。

该模型以 Host loopback 与 SSH tunnel 作为访问边界，不提供多用户隔离。proxy 使用
`AUTH_ALLOWED_EMAILS` 将注册限制为固定本地用户，并拒绝来自客户端的 Better Auth
mutation，避免 logout 或账号修改使共享 session 失效；不直接写入 Better Auth
database schema。

## Persistence

`/var/lib/codespace/lobehub` 是唯一持久化目录，保存 PostgreSQL cluster 与首次启动
生成的 LobeHub encryption/auth keys 及自动认证密码。image 只携带 database binary、
extension 和 migration，不携带生成的 database cluster。首次启动使用标准 `initdb`
创建 cluster，LobeHub 官方 launcher 幂等执行 schema migration。

这种布局允许替换 application container 而不改变数据库身份，同时避免把可变数据库
文件固化进 OCI layer。

## Scope

该最小部署支持对话、历史记录和 agent 配置。文件上传、知识库、Redis cache、Web
search 与多用户外部认证不属于此 Service；需要这些能力时应采用 LobeHub 官方
multi-container deployment。
