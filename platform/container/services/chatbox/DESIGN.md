# Chatbox Service Design

## Image Build

Chatbox 不发布 Web container image。该 image 从固定的 `v1.23.2` tag 构建官方 Web
产物，builder 使用上游要求的 Node.js 22 与 pnpm 10；最终 image 只保留静态资源和
Nginx。

构建时对上游 defaults 应用一个最小 patch。新的浏览器 profile 首次打开时会创建
`Local SGLang` custom provider，选择当前 SGLang Service 的默认模型，并关闭
analytics。Chatbox 后续仍通过原生 IndexedDB settings 管理配置，image 更新或
container 重建不会覆盖用户已经保存的浏览器配置。

## Runtime

Nginx 在容器接口 `3212` 提供 single-page application，并把同源 `/v1` 请求转发到
`CHATBOX_API_UPSTREAM`。默认 upstream 是 Podman bridge gateway 上的
`http://10.88.0.1:8003`；Host bridge subnet 不同时由 Service 配置覆盖。

浏览器不直接访问 bridge gateway，因此不依赖 SGLang 的 CORS 配置。Chatbox 仍按
OpenAI-compatible protocol 发送请求，`local` 只是满足客户端字段校验的无权限
占位值，不是 OpenAI credential。

## Persistence And Access

会话、设置和附件元数据保存在访问浏览器的 IndexedDB 中，Service 不挂载数据目录，
也不引入 database 或 authentication。Host 只向 loopback 发布端口，访问边界由 SSH
tunnel 提供；不同浏览器 profile 互不共享数据。
