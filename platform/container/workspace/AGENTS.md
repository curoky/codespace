# Workspace Image

本目录构建 `src/codespace` 唯一支持的 Workspace runtime，只由 control plane
启动，不提供 standalone 或旧 runtime contract。构建、启动与 Agent contract 见
[`DESIGN.md`](DESIGN.md)。

## Ownership

- `Dockerfile`、`config/` 与 `scripts/` 拥有 image build；`rootfs/` 拥有运行期
  filesystem、helper 与 s6 graph；`agent/` 拥有 control UDS API。
- `rootfs/home/x/` 是 Workspace-owned home 配置的唯一 source；Host 只能通过
  platform 层声明的相对 symlink 消费选定文件，不建立副本。
- s6 bootstrap 与安装器由本目录持有；Service image 只能复用它们，并自行持有
  service definition。

## Runtime

- build context 固定为仓库根目录；使用 `build.sh` 或 `task platform:workspace`
  构建，不从本目录直接执行 `docker build`。
- 运行资产放在 `/opt/codespace/`；image 不包含 repository checkout 或 Host
  固定路径。
- 控制面只挂载一个 editor cache root，不得感知或单独挂载具体 IDE 路径。
- IDE `bin` 与 `extensions` 由 image home 固定链接到 `/cache`。默认 extensions
  与各 IDE 的绝对路径 manifest 在 build 时生成，运行期只播种尚无 manifest 的
  cache，不合并或恢复用户之后删除的 extension。
- `rootfs/` 拥有 Workspace SSH authorized key 与 host key；Host client bundle
  必须与这两项 trust material 保持一致。
- `workspace-init` 只负责 Workspace 数据；`home-init` 只负责用户与 editor state。
- 服务依赖必须表达在 s6 graph 中，不在 runtime helper 内轮询其他服务。
- SSHD 固定监听容器 `0.0.0.0:22`，Workspace 固定使用 bridge network；Host
  loopback forwarding 与持久 macOS SSH route 属于 control plane 和 Host client。
- 无认证 file service 必须固定监听容器 loopback，不提供 bind override，只经 SSH
  tunnel 或容器内进程访问；写权限仅授予 `/upload`，Workspace 与日志视图只读。

## Security

- deploy private key 只在 Workspace 内生成；Agent 只返回 public key。
- Agent 只监听 control UDS；外层目录保持私有并只经 SSH forwarding 访问。
- `gh-login` 只从 private secret 的 stdin 读取 token；token 不进入 argv、
  container environment 或 s6 environment snapshot。
- encryption 只作用于 Workspace 数据；必须显式启用且缺少 key 时 fail-fast，
  不降级为明文。

## Verification

- Workspace image 验收位于 `tests/test_image.py`，只在 Dockerfile 的隔离
  `workspace-test` stage 中以用户 `x` 对已组装镜像运行；不要为兼容宿主机环境而
  mock Linux filesystem、权限或 runtime helper。
- 发布 stage 必须通过 test marker 依赖 `workspace-test`，确保普通镜像构建也执行
  验收；测试产生的 Workspace、editor cache 与 deploy key 不得进入发布层。
- `task test` 不构建或验收 Workspace image；修改 image contract 后运行
  `task platform:workspace`，提交前仍运行仓库级 `task check:full`。

mount、s6 dependency、Agent protocol 或 managed runtime input 变化时，同步
control plane 调用方与行为测试。home 或 SSH contract 变化时同步 macOS client
bundle；s6 bootstrap 或 dependency 变化时同步 WSL 复用方并验证 Service image。
