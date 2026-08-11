<!-- markdownlint-disable MD013 -->

# Codespace 多架构镜像构建访问 GHCR 超时排查

## 1. 文档状态

- 调查时间：2026-08-02
- 涉及 workflow：`.github/workflows/build-codespace-image.yaml`
- 涉及 Dockerfile：`images/dev/Dockerfile`
- 涉及 package manifest：`images/dev/script/binman.yaml`
- 涉及外部项目：`curoky/standalone-binaries` 的 `cmd/binman`
- 当前状态：已定位到客户端请求模型和共享网络路径之间的触发关系；根修复已完成本地实现级验证，仍需在新的 GitHub Actions runner 上完成四组压力 A/B 和完整 workflow 回归

本文记录完整排查过程，包括已验证事实、被排除方向、失败实验、当前根因边界、修复设计和剩余验证。文中不会把没有服务端证据支持的推断写成确定结论。

### 1.1 调查目标与成功标准

本次任务不是让构建“暂时能过”，而是回答以下问题：

1. `curl: (28)` 发生在 DNS、TCP、TLS、HTTP 还是 OCI 协议层。
2. 故障是否由 QEMU arm64 特有行为导致。
3. 为什么同一个 multi-platform build 中 amd64 可以访问 GHCR，而 arm64 连续超时。
4. 哪个组件制造了触发故障的 workload。
5. 根修复应落在 `devspace`、BuildKit 配置还是 `standalone-binaries`。
6. 修复是否会以明显降低大量 package 下载速度为代价。

成功标准分为两层：

- **机制级成功**：用测试证明认证状态被复用、请求并发受控，并且不改变 package
  解析结果。
- **系统级成功**：在同一个 GitHub-hosted runner 上完成旧版与修复版压力 A/B，
  最后通过无 cache 的完整 amd64/arm64 Action。

因此，下列方式不能单独作为完成标准：

- 把 `stage_sb` 改为 `$BUILDPLATFORM`，绕开 QEMU。
- 固定 GHCR IP。
- 继续增加 curl retry。
- 只让某一次有 cache 的 Action 偶然成功。

### 1.2 两个仓库的职责边界

问题跨越两个仓库：

| 仓库                         | 本次相关职责                                                          |
| ---------------------------- | --------------------------------------------------------------------- |
| `curoky/devspace`            | 定义 Codespace image、multi-platform workflow 和 134 package manifest |
| `curoky/standalone-binaries` | 发布 package OCI artifact、bootstrap installer 和 `bm` 客户端         |

`devspace` 不包含 `bm` 的 Go 源码。`stage_sb` 的完整获取链路是：

```text
devspace Dockerfile
  |
  | curl raw.githubusercontent.com/.../cmd/binman/install.sh
  v
standalone-binaries install.sh
  |
  | anonymous GHCR challenge + token + manifest + blob
  v
ghcr.io/curoky/standalone-binaries:binman-<architecture>
  |
  | extracted as /opt/sb/bin/bm
  v
bm sync /tmp/binman.yaml
  |
  | resolve and download 134 package tags
  v
ghcr.io/curoky/standalone-binaries:<package>-<architecture>
```

这一区分决定修复归属：

- Dockerfile 可以改变调用方式或 pin 版本，但无法直接修复 `bm` 的请求模型。
- `bm` 的 Puller 复用和并发逻辑必须在 `standalone-binaries` 中修改并重新发布。
- 新 `bm` 发布前，`devspace` Action 仍会 bootstrap GHCR 上的旧 artifact。

当前获取链路不是 hermetic 的：

- Dockerfile 从 `standalone-binaries/refs/heads/master` 获取 `install.sh`。
- installer 拉取可变 tag `binman-<architecture>`，而不是固定 OCI digest。
- package manifest 中的 package 也按可变 tag resolve。

因此，同一个 `devspace` commit 在不同时间可能消费不同版本的 installer、`bm` 和 package
artifact。本文记录外部仓库在调查时的源码快照 `58b877e`，但没有独立的 attestation
证明当时 GHCR 上每个 `binman-<architecture>` blob 一定由该 commit 构建。客户端行为、
日志和源码实现相符，但这不等价于完整的 artifact provenance 证明。

后续正式验证至少应记录：

```text
install.sh source commit
binman manifest digest
binman layer digest
bm binary sha256
package manifest git commit
```

完成根修复后，还应评估让 Dockerfile pin installer commit 和 `bm` OCI digest，或由发布
流程生成可审计的版本映射。否则即使修复验证通过，未来也难以精确重放同一依赖集合。

workflow 中的 `docker/login-action` 用于 BuildKit 拉取、推送 image 和 cache。Dockerfile
内部的 `install.sh` 与 `bm` 不会自动继承该 Docker credential；它们按照
`standalone-binaries` 的设计使用 anonymous pull token。因此，“workflow 已登录
GHCR”不等于 `stage_sb` 内部的每个 OCI 请求复用了同一个认证 transport。

### 1.3 Workflow 执行拓扑

workflow matrix 包含：

```text
debian:10
debian:11
debian:12
debian:13
ubuntu:26.04
```

需要区分两种并行：

1. **Matrix 并行**：每个 base image job 使用独立 GitHub-hosted runner，彼此不共享
   BuildKit daemon 或网络 namespace。
2. **Platform 并行**：每个 matrix job 内，一次 `buildx` 同时构建
   `linux/amd64,linux/arm64`；这两个 platform 使用同一 runner 上的 BuildKit daemon
   和 host 网络出口。

本次发现的相互影响发生在第二种并行内部，不是不同 matrix job 之间。

另一个容易误解的细节是：

```dockerfile
FROM docker.io/debian:latest AS stage_sb
```

`stage_sb` 不使用 matrix 的 `BASE_IMAGE`。不同 matrix job 虽然最终 base image 不同，
但负责 bootstrap `bm` 和同步 standalone package 的 stage 内容相同。不同 matrix
结果仍可能因独立 runner、DNS edge、cache 和并发时序而不同。

当前 workflow 同时配置了：

- build step 的 `network: host`。
- buildx driver 的 `network=host`。
- BuildKit daemon 的 `--oci-worker-net=host`。

这些设置消除了常见的 bridge/NAT 配置差异，但也意味着同一个 job 内两个 platform
的网络流量汇聚到同一个 runner egress。它们不是两个网络隔离的远端构建机。

### 1.4 问题出现前的变更历史

下表只描述与本问题直接相关的演进，不把提交意图当成已验证效果：

| 提交      | 时间       | 变化                                                   | 与调查的关系                                                 |
| --------- | ---------- | ------------------------------------------------------ | ------------------------------------------------------------ |
| `5f5970d` | 2026-07-30 | 从旧 `sb` client 迁移到 `bm sync`                      | 引入当前 OCI client 路径                                     |
| `04bb3d1` | 2026-07-31 | workflow 增加 QEMU 和 amd64/arm64 multi-platform build | 引入同 job 双 platform 并行                                  |
| `952e3f0` | 2026-08-02 | Dockerfile 按 `TARGETARCH` 选择 `bm` artifact          | 两个平台开始消费各自架构的 `bm`                              |
| `7a337e7` | 2026-08-02 | build step 增加 `network: host`                        | 第一次网络规避尝试                                           |
| `512e80c` | 2026-08-02 | 临时加入 DNS、IPv4/IPv6、token debug                   | 早期可观测性尝试                                             |
| `c76a15b` | 2026-08-02 | 移除临时 debug，并修复另一个 QEMU Nix seccomp 问题     | 说明仓库中确有另一个独立 QEMU 问题，不能与 GHCR 超时混为一谈 |
| `5e4c717` | 2026-08-02 | buildx driver 增加 `network=host`                      | 进一步排除 builder bridge                                    |
| `8d6bb34` | 2026-08-02 | 增加 BuildKit entitlement 和 worker host network       | 确认 daemon/worker 网络配置                                  |
| `d93d0c5` | 2026-08-02 | 失败后启动 tmate                                       | 允许进入 runner 现场排查                                     |
| `d3aa77c` | 2026-08-02 | `limit-access-to-actor: false`                         | 解决 tmate actor key 不匹配，调查快照 commit                 |

在 `5e4c717` 和 `8d6bb34` 后 workflow 仍可复现，因此“再增加一层 host network 配置”
不是充分修复。

`512e80c` 中加入 Dockerfile 的 debug layer 后又在 `c76a15b` 中移除，避免把一次性
诊断代码长期留在 image。本文档承担长期保留证据和推理过程的职责。

### 1.5 调查快照与 ID 类型

调查涉及三种容易混淆的 ID：

| 类型                  | 示例                        | 生命周期与用途                                                      |
| --------------------- | --------------------------- | ------------------------------------------------------------------- |
| GitHub Actions run ID | `30739462661`               | GitHub 上长期可查的一次 workflow run                                |
| GitHub Actions job ID | `91480045405`               | run 中一个 matrix job                                               |
| BuildKit history ID   | `5f3rfovuhewp1k3g7z7l40ls0` | 特定 runner 本地 builder 的一次 build 记录，runner 销毁后不可再访问 |

两次主要现场调查使用同一个 `devspace` commit：

```text
d3aa77cc52f210aebab9a776a6a058e8461610aa
```

外部 `standalone-binaries` 调查快照为：

```text
58b877e
```

主要 run：

| 调查   |           Run | Event             | 主要现场 job                   | BuildKit history            |
| ------ | ------------: | ----------------- | ------------------------------ | --------------------------- |
| 第一次 | `30739462661` | push              | 两个失败 job 中的 tmate runner | `jkoswlztzoauu8ltjrw2w588j` |
| 第二次 | `30741650188` | workflow dispatch | Debian 11，job `91480045405`   | `5f3rfovuhewp1k3g7z7l40ls0` |

BuildKit history ID 是 runner-local 证据索引，不是 GitHub API 可查询的 ID。

### 1.6 tmate 接入上下文

第一次加入 tmate 时，`limit-access-to-actor: true` 要求连接者提供与触发 actor 匹配的
GitHub SSH key，现场没有可匹配私钥，因此最初链接无法进入。提交 `d3aa77c` 临时改为
`false` 后，持有随机 tmate session 地址即可连接，调查才得以继续。

当前 workflow 的实际行为是：

- `debug_tmate` input 控制 matrix `fail-fast`。
- tmate step 本身只有 `if: failure()`，没有再判断 `debug_tmate`。
- 因此任何失败 job 都会尝试启动 tmate，而不只是在 input 为 `true` 时。

`limit-access-to-actor: false` 适合短期现场调试，但访问控制依赖高熵 session URL。
调查结束后应重新评估是否恢复 actor 限制或改用明确的 authorized key。

本地连接第二个 session 时还遇到一个与远端无关的问题：本机 SSH config 试图在只读的
`/home/x/.ssh` 创建 ControlPath。使用以下选项禁用 connection multiplexing 后成功：

```bash
ssh -o ControlMaster=no -o ControlPath=none <tmate-session>
```

两次调查使用过多个 tmate session URL。它们是短期 bearer credential，已经失效，
不应写入长期文档；run 和 job ID 才是长期索引。

### 1.7 当前代码与临时资产状态

截至本文更新：

- `devspace` 的 Dockerfile 未应用 `$BUILDPLATFORM` 或其他 workaround。
- `devspace` 未包含 `bm` 根修复代码。
- workflow 仍保留 host network 和 tmate 调试配置。
- 本仓库工作树新增的持久改动只有本文档。
- `bm` 修复原型位于本机 `/tmp/standalone-binaries` 临时 clone。
- runner 上的 pcap、临时 Dockerfile、四个 A/B 二进制和 BuildKit history 都属于
  ephemeral 调查资产，session/runner 结束后不应假设仍存在。
- 没有创建 commit，也没有发布新的 `bm` artifact。

这意味着“已完成实现级测试”与“线上 Action 已使用修复版”是两个不同状态。当前仍是
前者，不能宣称问题已在线上修复。

### 1.8 证据等级

本文按以下等级使用证据：

- **直接观测**：Action log、BuildKit history、进程列表、`curl` timing、`tcpdump`
  pcap、`ss` 输出和测试结果。
- **实现事实**：当前 commit 中 workflow/Dockerfile，以及
  `standalone-binaries@58b877e` 的 Go 源码。
- **实验推断**：由受控 A/B 支持的因果关系，例如“QEMU 不是必要条件”。
- **未知项**：没有服务端或网络设备 telemetry 支持的具体丢包位置。

后文的“已确认”只用于前三类中有明确证据支持的结论；对未知项保持边界。

### 1.9 调查时间线

以下时间线使用 Asia/Singapore（UTC+8），把提交、Action 和现场实验放在同一顺序中：

| 时间                   | 事件                                    | 结果                                     |
| ---------------------- | --------------------------------------- | ---------------------------------------- |
| 2026-07-30             | `devspace` 从旧 `sb` client 迁移到 `bm` | `stage_sb` 开始执行 `bm sync`            |
| 2026-07-31             | workflow 增加 QEMU 和双 platform build  | amd64/arm64 开始在同一 matrix job 内并行 |
| 2026-08-02 00:24       | Dockerfile 增加 `TARGETARCH` 映射       | 两个平台下载各自架构的 `bm`              |
| 2026-08-02 01:50–12:43 | 逐层增加 host network 和 BuildKit flags | 故障仍可复现                             |
| 2026-08-02 13:19       | 增加失败后 tmate                        | 初始 actor key 限制阻止连接              |
| 2026-08-02 16:16       | tmate 临时改为不限制 actor              | 可进入失败 runner                        |
| 2026-08-02 16:16–17:22 | run `30739462661`                       | 完成第一次现场调查和抓包                 |
| 2026-08-02 17:22–17:59 | run `30741650188`                       | 再次复现并发现跨 platform 精确时序       |
| 第二次 tmate 期间      | 现场构建 `old16/reuse16/reuse8/reuse4`  | 二进制准备完成，正式 A/B 前 session 退出 |
| session 结束后         | 本地补充 `httptest` 回归和 Go 验证      | 认证复用、并发上限、race/vet/build 通过  |

该时间线说明结论不是从一次失败日志直接推导，而是经历了网络配置排除、独立基线、
最小复现、pcap、原生/QEMU A/B、源码分析和机制级测试。

## 2. 故障现象

`Build codespace images` 同时构建 `linux/amd64` 和 `linux/arm64` 镜像。`stage_sb` 先通过 `install.sh` 从 GHCR 下载 `bm`，再用它同步 134 个 standalone package：

```dockerfile
RUN case "${TARGETARCH}" in \
    amd64) binman_arch=linux-x86_64 ;; \
    arm64) binman_arch=linux-arm64 ;; \
    *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
  esac \
  && curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /opt/sb/bin --arch "${binman_arch}" \
  && /opt/sb/bin/bm --arch "${binman_arch}" sync /tmp/binman.yaml
```

失败集中表现为 arm64 阶段无法与 `ghcr.io:443` 建立 TCP 连接：

```text
curl: (28) Connection timed out after 20002 milliseconds
> registry challenge attempt 6/6 remote_ip= http=000 connect=0.000000 tls=0.000000
```

这里存在两层 curl：

1. Dockerfile 外层 curl 从 `raw.githubusercontent.com` 获取 `install.sh`。
2. `install.sh` 内部 curl 依次访问 GHCR challenge、token、manifest 和 blob endpoint。

失败日志已经打印：

```text
> Installing bm (linux-arm64) into /opt/sb/bin
```

这说明外层脚本下载和 Bash 启动已经成功。报错中的 `registry challenge attempt` 来自
`install.sh` 内部第一步，即访问 `https://ghcr.io/v2/`，还没有下载 `bm` manifest
或 blob，更没有启动 `bm sync`。

同一时间，另一个 platform 的 `bm sync` 可以已经开始。必须从完整 multi-platform
日志按时间合并两个 platform，而不能只看失败 platform 的局部尾部日志。

这里几个字段很关键：

- `http=000`：没有收到 HTTP 响应。
- `connect=0.000000`：TCP connect 没有完成。
- `tls=0.000000`：尚未进入 TLS handshake。
- 每次约 20 秒后超时：与 installer 的 `--connect-timeout 20` 一致。

因此，直接故障层级是 **TCP 建连超时**，不是 DNS、HTTP、TLS、OCI manifest 解析或 artifact 内容错误。

## 3. 初始假设

故障表面只出现在 QEMU arm64 阶段，因此最初考虑了以下方向：

1. QEMU user-mode networking 或 syscall emulation 存在缺陷。
2. arm64 Debian 的 `curl`、glibc、CA certificate 或 DNS 行为不同。
3. BuildKit 容器网络没有真正使用 host network。
4. GitHub Actions runner 到 GHCR 的某个 edge IP 不稳定。
5. 多平台并行构建产生了连接竞争或上游网络保护。
6. `bm sync` 对 GHCR 发起的并发 OCI 请求过多。

排查没有预设 QEMU 一定是根因，而是逐层验证 DNS、TCP、TLS、HTTP、进程并发和客户端实现。

## 4. 现场环境

两次调查均通过失败 job 后的 tmate session 进入 GitHub-hosted runner。

已确认的 runner 环境：

| 项目                    | 值                 |
| ----------------------- | ------------------ |
| 宿主架构                | `x86_64`           |
| CPU                     | 4 vCPU             |
| 内存                    | 约 16 GiB          |
| BuildKit                | `v0.31.2`          |
| QEMU/binfmt image       | `binfmt/e29e7d7`   |
| QEMU                    | `v10.2.3`          |
| binfmt flags            | `POCF`             |
| builder driver          | `docker-container` |
| BuildKit worker network | host               |
| build network           | host               |

BuildKit daemon参数包括：

```text
--allow-insecure-entitlement network.host
--allow-insecure-entitlement security.insecure
--oci-worker-net=host
```

`docker buildx history inspect` 也显示：

```text
Network: host
```

这意味着 multi-platform build 中的 amd64 和 arm64 build container 共用 runner/BuildKit 的 host 网络出口。一个平台制造的连接压力可能影响另一个平台，不能把两条 platform log 当成网络上完全隔离的任务。

## 5. 第一次 tmate 调查

第一次主要调查对应 GitHub Actions run：

```text
https://github.com/curoky/devspace/actions/runs/30739462661
```

run 由 `d3aa77c` 的 push 触发，matrix 结果为：

| Matrix       | Build step | Job 结论  | 说明                                               |
| ------------ | ---------- | --------- | -------------------------------------------------- |
| Debian 10    | failure    | cancelled | build 失败后 tmate 等待约 60 分钟，最终 job 被取消 |
| Debian 11    | success    | success   | 完成 multi-platform build 和 push                  |
| Debian 12    | success    | success   | 完成 multi-platform build 和 push                  |
| Debian 13    | failure    | failure   | build 失败，tmate step 约 60 分钟后失败            |
| Ubuntu 26.04 | success    | success   | 完成 multi-platform build 和 push                  |

同一 commit、同一 workflow 配置下，3 个独立 runner 成功，2 个失败。这说明问题不是
某个 Dockerfile 语法、package tag 缺失或 arm64 artifact 永久不可用；否则所有 matrix
中的相同 `stage_sb` 都应确定性失败。结果更符合 runner 网络路径、cache 和双 platform
时序共同影响的瞬态故障。

job 的最终 conclusion 还受到 tmate step 影响。例如 Debian 10 的 build step 已经失败，
但 job 最终显示 cancelled；不能只看 job conclusion 判断 image build 是否成功。

### 5.1 验证宿主网络基线

在 runner 宿主上访问以下目标均正常：

- `github.com`
- `raw.githubusercontent.com`
- `ghcr.io`

DNS 能解析 GHCR IPv4 地址，空闲时 `curl https://ghcr.io/v2/` 能快速收到预期的 `401 Unauthorized`。

这排除了 runner 持续断网、GHCR 持续不可达和固定 DNS 配置错误。

### 5.2 验证 QEMU arm64 网络基线

单独运行 arm64 Debian container，通过 QEMU 连续执行：

- GHCR registry challenge。
- 下载 `raw.githubusercontent.com` 上的 `install.sh`。
- 普通 DNS 和 HTTPS 请求。

这些测试均能成功。

因此，不存在“arm64 QEMU 一运行 curl 就必然失败”的确定性缺陷。QEMU 仍可能放大时序或性能差异，但不能解释故障本身。

### 5.3 检查原始 BuildKit history

原始失败 build history ID：

```text
jkoswlztzoauu8ltjrw2w588j
```

history 显示：

- arm64 registry challenge 连续 6 次失败。
- 每次都在 20 秒 TCP connect timeout 后返回。
- 同一时段 amd64 对同一个 GHCR 地址能在约 3–6 ms 建连。

这说明：

1. DNS 已返回地址。
2. GHCR 不是全局不可达。
3. 超时具有并发或流量相关性，而不是简单的目标服务宕机。

### 5.4 最小 multi-platform 复现与抓包

构造最小 multi-platform build，让一个平台执行真实 `bm sync`，另一个平台同时反复访问 GHCR challenge endpoint。

问题可稳定复现：探测方连续 6 次 challenge connect timeout。

`tcpdump` 中对应连接只看到客户端发出的 SYN 及其重传，没有看到 SYN-ACK：

```text
client -> ghcr.io:443  SYN
client -> ghcr.io:443  SYN retransmit
client -> ghcr.io:443  SYN retransmit
...
```

这将故障层级从“curl 报连接超时”进一步确认到“新建 TCP flow 的 SYN 没有得到响应”。抓包没有显示 HTTP 429、403 或 registry error body。

### 5.5 宿主与 QEMU A/B

在真实 `bm sync` 负载期间，同时从宿主原生进程和 arm64 QEMU container 连续探测 GHCR。

结果：

| 探测方               | 总次数 | 成功 | TCP connect timeout |
| -------------------- | -----: | ---: | ------------------: |
| runner 宿主原生 curl |     80 |   20 |                  60 |
| QEMU arm64 curl      |     80 |   22 |                  58 |

两者失败率几乎一致。

这项实验是排除 QEMU 根因的关键证据：**只要与真实 `bm sync` 共用网络出口，原生 amd64 curl 和 QEMU arm64 curl 都会大量超时。**

`bm sync` 本身最终约 5 分 55 秒完成，说明已有连接或部分请求仍可继续，主要受影响的是同期新建的 GHCR TCP flow。

### 5.6 实验有效性与废弃数据

调查早期写过一版 shell 并发压力脚本，尝试通过导出 function 再交给子 shell 并行执行。
Debian 的 `/bin/sh` 不支持该 Bash function export 用法，子进程没有执行预期请求。

该实验已判定无效，所有输出和计数均废弃，不参与本文任何结论。后续压力数据只采用：

- 可直接看到命令和退出码的 curl loop。
- 真实 `bm sync` workload。
- BuildKit multi-platform build。
- pcap 中可对应到具体 probe 的 TCP flow。
- Go `httptest` 中由进程内 atomic counter 记录的请求数和峰值并发。

宿主/QEMU 的 `80` 次 A/B 采用同一时间窗口、同一 GHCR endpoint 和相同 connect
timeout。它证明 QEMU 不是发生超时的必要条件，但不单独证明 SYN-ACK 丢失的设备位置。

## 6. 第二次 tmate 调查

第二次调查对应手动触发的 GitHub Actions run：

```text
https://github.com/curoky/devspace/actions/runs/30741650188
```

仍使用 `d3aa77c`，matrix 结果为：

| Matrix       | Build step | Job 结论  | 说明                                     |
| ------------ | ---------- | --------- | ---------------------------------------- |
| Debian 10    | success    | success   | 完成 build 和 push                       |
| Debian 11    | failure    | failure   | 进入并完成 tmate 调查；本节的主要 runner |
| Debian 12    | failure    | cancelled | 进入 tmate，run 结束时被取消             |
| Debian 13    | success    | success   | 完成 build 和 push                       |
| Ubuntu 26.04 | success    | success   | 完成 build 和 push                       |

第一次失败的 Debian 10 和 Debian 13 在第二次成功，第一次成功的 Debian 11 和 Debian
12 在第二次失败。这是另一个重要反证：失败不与最终 base image 版本稳定绑定。

Debian 11 的 job ID 是：

```text
91480045405
```

该 runner 上的本地 BuildKit history ID 是：

```text
5f3rfovuhewp1k3g7z7l40ls0
```

### 6.1 再次复现

第二次 GitHub Actions build history：

```text
5f3rfovuhewp1k3g7z7l40ls0
```

该 history 明确显示：

```text
Platforms: linux/amd64, linux/arm64
Network: host
No Cache: true
```

因此第二次复现不是命中旧 `stage_sb` cache 后留下的历史错误，两个 platform 都在同一
次无 cache build 中实际执行相关 RUN step。

环境与第一次一致：

- BuildKit `v0.31.2`
- host network
- 4 vCPU
- 约 16 GiB 内存
- multi-platform 并行构建

该 build 在约 5 分 8 秒后失败。

### 6.2 发现跨平台时序关系

完整日志显示 amd64 顺利完成 `bm` bootstrap：

```text
#31 0.401 > registry challenge attempt 1/6 ... http=401 connect=0.003259
#31 0.469 > registry token attempt 1/6 ... http=200 connect=0.003366
#31 0.550 > manifest attempt 1/6 ... http=200 connect=0.002756
#31 1.111 > blob attempt 1/6 ... http=200 connect=0.051127
#31 1.351 > Syncing 134 unique package(s) from /tmp/binman.yaml...
#31 1.352 > Resolving 134 package(s)...
```

arm64 此时正在执行相同 stage，但由于 QEMU 下前置包安装更慢，刚进入 `bm` bootstrap。它的 6 次 challenge 全部超时：

```text
89.96  140.82.114.34 ...
110.1  curl: (28) Connection timed out after 20002 milliseconds
110.1  > registry challenge attempt 5/6 ... http=000
112.3  140.82.114.34 ...
132.5  curl: (28) Connection timed out after 20002 milliseconds
132.5  > registry challenge attempt 6/6 ... http=000
```

关键时序为：

1. amd64 先完成 bootstrap。
2. amd64 开始并发 resolve 134 个 package。
3. arm64 随后开始 bootstrap，需要新建 GHCR TCP 连接。
4. arm64 的新连接连续进入 SYN-only timeout。

因此，错误虽然打印在 arm64 `curl` 中，但 arm64 是共享网络压力下的受害者，不是负载制造者。

### 6.3 空闲基线复验

build 结束、没有 `bm sync` 运行时，在同一 runner 连续 5 次访问 GHCR：

```text
1 code=401 ip=140.82.112.33 connect=0.004515
2 code=401 ip=140.82.112.33 connect=0.002569
3 code=401 ip=140.82.112.33 connect=0.003028
4 code=401 ip=140.82.112.33 connect=0.002503
5 code=401 ip=140.82.112.33 connect=0.002196
```

5 次均成功，进一步支持“故障只在高并发 workload 期间出现”。

## 7. `bm` 实现分析

故障 workload 来自外部仓库 `curoky/standalone-binaries`，调查时 master commit 为：

```text
58b877e
```

### 7.1 package 数量

`images/dev/script/binman.yaml` 包含 116 个顶层 package 和 18 个 profile
package，合并后是日志报告的 134 个唯一 package。一次 sync 会先 resolve 全部 tag，
再并发下载需要更新的 layer。

### 7.2 外层并发

`cmd/binman/main.go` 中并发上限硬编码为：

```go
const maxParallel = 16
```

`cmd/binman/registry.go` 的 resolve 和 download 两个阶段都使用：

```go
group.SetLimit(maxParallel)
```

因此，一次 134 package sync 会以最多 16 路并发执行 OCI resolve，随后最多 16 路并发读取 blob。

### 7.3 每个 tag 都创建独立 Puller

旧实现对每个 package tag 调用：

```go
image, err := remote.Image(reference)
```

`go-containerregistry` 的 `remote.Image` 在没有传入 `remote.Reuse` 时，每次从新的 Puller/fetcher 状态开始。对于同一 repository 下的 134 个 tag，这会重复执行：

- registry `/v2/` challenge。
- anonymous token exchange。
- transport/fetcher 初始化。
- manifest 请求。

外层同时运行最多 16 个独立 `remote.Image`，会集中制造新连接、challenge 和 token 请求。

### 7.4 可用的库级复用机制

项目使用：

```text
github.com/google/go-containerregistry v0.21.7
```

该版本提供：

```go
remote.NewPuller(options ...Option)
remote.Reuse(puller)
remote.WithJobs(jobs)
```

库源码说明 `Reuse` 会在可能时复用 token exchange，并避免冗余 HEAD 请求。`Puller` 内部以 repository context 为 key 缓存 fetcher，正好适用于本项目“同一 repository 下 134 个 tag”的布局。

库内部默认 jobs 为 4，但旧 `bm` 的主要问题不是简单忽略这个默认值，而是在它外面再并发创建最多 16 个彼此不共享认证状态的 `remote.Image` 调用。

## 8. 根因结论与边界

### 8.1 已确认的客户端根因

可由项目代码控制并已被实验支持的根因是：

> `bm` 在解析大量 tag 时，以 16 路外层并发为每个 tag 创建独立 registry Puller，重复建立认证和 manifest 请求；multi-platform build 又让 amd64 和 QEMU arm64 共用 BuildKit host 网络出口。amd64 的 134 package resolve 突发流量使同期新建的 GHCR TCP flow 大量得不到 SYN-ACK，最终由稍晚启动的 arm64 bootstrap curl 报出 connect timeout。

“QEMU arm64 更容易看到错误”主要来自构建时序：

- 原生 amd64 更快进入 `bm sync`，成为负载制造者。
- QEMU arm64 前置步骤更慢，恰好在负载高峰开始 bootstrap，成为失败方。

### 8.2 已确认的网络表现

已确认：

- DNS 能正常解析。
- TCP SYN 已从 runner 发出。
- 失败 flow 没有收到 SYN-ACK。
- 原生和 QEMU probe 在 `bm sync` 压力下具有近似失败率。
- 空闲时同一 runner 到 GHCR 建连正常。
- 没有收到 HTTP 429、403 或其他服务端拒绝响应。

### 8.3 尚不能确认的服务端或基础设施细节

当前证据不足以判断 SYN-ACK 具体在哪一层被丢弃。可能位置包括：

- GitHub-hosted runner 的 egress/NAT/conntrack 路径。
- GitHub 网络边缘。
- GHCR 前端或其 DDoS/abuse protection。
- 中间网络设备。

不能声称“GHCR 官方限流阈值已被触发”，原因是：

- 没有 HTTP 429 或 403。
- 没有服务端 request ID 或限流日志。
- GHCR 公开文档没有提供与本实验直接匹配的 TCP connection 阈值。

严格结论应保持为：

> `bm` 的 16 路独立 OCI auth/manifest 请求突发与新 GHCR TCP flow 的 SYN-ACK 黑洞高度相关；客户端请求模型是可修复的触发条件，具体丢包设备尚未被观测到。

## 9. 已排除或拒绝的方向

### 9.1 将 `stage_sb` 改到 build platform

候选 workaround：

```dockerfile
FROM --platform=$BUILDPLATFORM ...
```

这样可以绕过 QEMU 执行 `bm`，但不能消除并发 OCI 请求，也不能解释宿主原生 curl 在相同负载下同样超时。该方案改变构建语义，只隐藏触发时序，不是根修复，因此被拒绝。

### 9.2 仅增加 curl retry

`install.sh` 已有 6 次、每次 20 秒的 retry。连续 SYN-only timeout 时，retry 只把失败延迟到约 2 分钟后，不能消除共享网络出口上的连接突发。

Retry 可作为瞬时网络故障的防御，但不能替代客户端并发和连接复用修复。

### 9.3 固定 GHCR IP

失败期间 DNS 已正常返回地址，且不同时间可解析到不同 GitHub edge IP。固定 IP：

- 无法修复同一网络路径上的新连接黑洞。
- 会绕开正常 DNS 负载调度。
- 容易因服务地址变化失效。

因此不采用。

### 9.4 仅启用 host network

workflow 已同时配置 BuildKit daemon、worker 和 build step 使用 host network，history 也确认 `Network: host`。继续叠加同类设置不会改变结果。

### 9.5 将问题归因于 arm64 curl 或 QEMU

单独 QEMU arm64 HTTPS 测试正常，真实 `bm sync` 压力下宿主与 QEMU curl 的失败率分别为 75% 和 72.5%。数据不支持 QEMU 特有故障结论。

## 10. 根修复设计

根修复应提交到 `curoky/standalone-binaries`，因为 `devspace` 只通过 `install.sh` 消费已发布的 `bm` artifact。

### 10.1 批次共享 Puller

一次批量 resolve 创建一个 Puller：

```go
puller, err := remote.NewPuller(remote.WithJobs(resolveParallel))
```

所有 tag 通过同一个 Puller：

```go
image, err := remote.Image(reference, remote.Reuse(puller))
```

预期效果：

- 同一 repository 只初始化一次 fetcher/auth transport。
- token exchange 可复用。
- HTTP transport 和连接池可复用。
- 不再为每个 tag 重复 registry challenge。

### 10.2 分离 resolve 和 download 并发

初始修复把统一的 `maxParallel` 从 16 降到 4，但这可能不必要地降低 blob download 吞吐。

更精确的最终设计应拆分为：

```go
const (
    resolveParallel  = 4
    downloadParallel = 16
)
```

理由：

- 已观测故障发生在 134 package resolve 期间。
- 第二次 build 中 amd64 尚未开始 blob download，arm64 bootstrap 已连续超时。
- resolve 会集中产生 auth、manifest 和新连接请求。
- blob download 更可能受总带宽限制，适当并发有助于吞吐。

最终数值应由同 runner A/B 决定，而不是仅凭经验固定为 4。

### 10.3 `outdated` 使用同一批量路径

旧 `cmdOutdated` 也并发调用 `remoteDigest`，每个 package 创建独立 Puller。修复应让它构造 `artifactRequest` 列表并调用共享 Puller 的 `resolveArtifacts`，避免保留另一条重复认证路径。

### 10.4 Retry 的位置

只有在连接复用和并发模型修复后，才考虑调整指数退避。Retry 应处理不可避免的瞬时网络故障，而不是掩盖稳定可复现的连接风暴。

## 11. 实现级回归测试

在 `/tmp/standalone-binaries` 临时 clone 中完成了修复原型和测试，没有修改 `devspace` 的 Dockerfile。

### 11.1 Bearer token 复用测试

使用 `httptest` registry middleware 模拟真实 Bearer challenge 和 token endpoint。

测试批量解析 4 个 tag，并统计 token endpoint 请求数。

旧实现结果：

```text
registry token requests=4 want 1
```

共享 Puller 后：

```text
registry token requests=1
```

这直接验证了修复消除了每个 tag 独立 token exchange，而不是仅靠降低并发改变时序。

### 11.2 resolve 峰值并发测试

middleware 在 manifest GET 上记录 active 和 peak，并人为延迟 50 ms，使请求重叠可观测。

对 8 个 tag：

```text
旧实现 peak registry concurrency=8
修复后 peak registry concurrency<=4
```

### 11.3 已通过的验证

修复原型已通过：

```text
CGO_ENABLED=0 go test ./cmd/binman
CGO_ENABLED=1 go test -race ./cmd/binman
CGO_ENABLED=0 go vet ./cmd/binman
CGO_ENABLED=0 go build ./cmd/binman
```

测试结果：

```text
go test:      PASS
go test-race: PASS
go vet:       PASS
go build:     PASS
```

这些测试证明实现正确性、并发安全和认证复用行为，但不等价于 GitHub Actions 网络压力回归。

## 12. 未完成的现场 A/B

第二次 runner 上已准备四个版本：

| 版本      | Puller        | 外层并发 |
| --------- | ------------- | -------: |
| `old16`   | 每个 tag 独立 |       16 |
| `reuse16` | 批次共享      |       16 |
| `reuse8`  | 批次共享      |        8 |
| `reuse4`  | 批次共享      |        4 |

现场构建后的 SHA-256：

```text
0d6c170a9c9324c83149b3e7369ca03cc5843037e5086024f5279ef6a9a33997  bm-old16
b22e1a0db1126f5a8c0343e579f277d04c2f340061582919a7bc81dabf54c868  bm-reuse16
eaf2107732f04083c9376dadd9c41d301019735a35033a7e3fdf0373e2c7d894  bm-reuse8
cf2054330924634815d3e4d8f07bd80767084666ee8f8c763699a840a85a8cd7  bm-reuse4
```

准备运行 A/B 时，调试 shell 因继承 `set -e`，执行 runner 中不存在的 `rg` 后退出，tmate session 随默认 shell 一同关闭。因此四组现场数据尚未采集，不能据此决定最终并发值。

这是一次调试流程错误，不是产品故障。后续 tmate 调试不得在主 shell 全局启用 `set -e`；长时间实验应放在独立脚本或 tmux window 中，并先检查所需命令是否存在。

## 13. 下一轮验证方案

### 13.1 固定变量

四组实验必须使用：

- 同一 GitHub Actions runner。
- 同一 BuildKit builder。
- 同一 GHCR DNS 和网络出口。
- 同一个 134 package manifest。
- 相同 cache 状态。
- 相同 probe 频率和 connect timeout。

实验顺序应交错或重复，避免网络随时间变化造成偏差，例如：

```text
old16 -> reuse16 -> reuse4 -> reuse8 -> reuse16 -> old16
```

### 13.2 分离 resolve 和 download

第一阶段只测 resolve：

- 为 134 个 package 准备已有 metadata。
- 执行 `bm outdated` 或等价的 `resolveArtifacts` workload。
- 不下载 blob。

这能直接测量：

- registry challenge 次数。
- token request 次数。
- manifest request 并发。
- 新建 TCP flow 数。
- SYN-only flow 数。
- 独立 GHCR probe timeout 数。
- resolve 总耗时。

第二阶段再测完整 sync：

- 清空 package cache。
- 完整下载 134 个 package。
- 分别记录 resolve、download 和总耗时。

这样可以避免把认证复用收益与 blob 吞吐混在一起。

### 13.3 观测项

每组至少记录：

| 指标                            | 目的                               |
| ------------------------------- | ---------------------------------- |
| resolve wall time               | 比较共享 Puller 和并发值的性能     |
| download wall time              | 判断降低 download 并发的代价       |
| total wall time                 | 判断真实用户体验                   |
| `/v2/` challenge 数             | 验证 transport 初始化复用          |
| token request 数                | 验证认证复用                       |
| manifest request 数             | 验证 workload 一致                 |
| TCP SYN 数                      | 衡量新连接压力                     |
| SYN retransmit/SYN-only flow 数 | 直接观察黑洞是否消失               |
| probe success/timeout           | 判断 workload 是否伤害同出口新连接 |
| peak established sockets        | 辅助判断连接池行为                 |

建议同时运行：

```bash
sudo tcpdump -i any -nn 'tcp dst port 443 and host <ghcr-ip>' -w /tmp/ghcr.pcap
```

以及固定频率 probe：

```bash
curl -4 -sS \
  --connect-timeout 3 \
  -o /dev/null \
  -w 'code=%{http_code} ip=%{remote_ip} connect=%{time_connect}\n' \
  https://ghcr.io/v2/
```

### 13.4 决策标准

优先选择以下最小改动：

1. 如果 `reuse16` 已无 probe timeout、无 SYN-only flow，且性能最好：
   - 保留 resolve/download 并发 16。
   - 只合入共享 Puller 和批量路径修复。
2. 如果 `reuse16` 仍不稳定，但 `reuse8` 稳定：
   - resolve 并发设为 8。
   - download 并发保持 16，另行验证。
3. 如果只有 `reuse4` 稳定：
   - resolve 并发设为 4。
   - download 并发通过完整 sync 数据决定，不直接跟随降到 4。

稳定标准：

- 134 tag resolve 连续多轮成功。
- 同期独立 GHCR probe 无 connect timeout。
- pcap 不再出现成批 SYN-only flow。
- Bearer token exchange 每个批次仅一次。

### 13.5 完整 workflow 回归

修复合入并发布新的 `binman-linux-x86_64` 和 `binman-linux-arm64` artifact 后：

1. 手动触发 `Build codespace images`。
2. 开启 `disable_docker_cache`，避免旧 `stage_sb` layer 掩盖问题。
3. 同时构建 `linux/amd64,linux/arm64`。
4. 覆盖至少一个此前稳定失败的 Debian matrix 项。
5. 最终再跑完整 distro matrix。

成功标准：

- arm64 bootstrap challenge 首次或正常 retry 后成功。
- 两个平台均完成 134 package sync。
- 没有 `curl: (28)`。
- 所有目标 image 和 cache 正常 push。

## 14. 证据索引与复核入口

### 14.1 仓库内长期证据

| 证据                | 路径或 commit                                  | 可复核内容                                       |
| ------------------- | ---------------------------------------------- | ------------------------------------------------ |
| 当前 workflow       | `.github/workflows/build-codespace-image.yaml` | matrix、QEMU、BuildKit network、tmate            |
| 当前 Dockerfile     | `images/dev/Dockerfile`              | `stage_sb`、`TARGETARCH`、bootstrap 和 sync 顺序 |
| package manifest    | `images/dev/script/binman.yaml`      | 116 个顶层 package 和 18 个 profile package      |
| multi-platform 引入 | `04bb3d1`                                      | QEMU setup 和 `linux/amd64,linux/arm64`          |
| `bm` 迁移           | `5f5970d`                                      | 从旧 `sb` client 切换到 `bm sync`                |
| host network 演进   | `7a337e7`、`5e4c717`、`8d6bb34`                | build step、driver 和 worker 三层配置            |
| tmate 演进          | `d93d0c5`、`d3aa77c`                           | debug input、failure step 和 access policy       |

可用以下命令复核提交演进：

```bash
git show 04bb3d1 -- .github/workflows/build-codespace-image.yaml
git show 5f5970d -- codespace/images/dev/Dockerfile
git show 7a337e7 -- .github/workflows/build-codespace-image.yaml
git show 5e4c717 -- .github/workflows/build-codespace-image.yaml
git show 8d6bb34 -- .github/workflows/build-codespace-image.yaml
git show d93d0c5 -- .github/workflows/build-codespace-image.yaml
git show d3aa77c -- .github/workflows/build-codespace-image.yaml
```

### 14.2 GitHub 上的长期证据

主要 run：

```text
https://github.com/curoky/devspace/actions/runs/30739462661
https://github.com/curoky/devspace/actions/runs/30741650188
```

可通过 GitHub CLI 重新查询 matrix 结果：

```bash
gh run view 30739462661 \
  --repo curoky/devspace \
  --json databaseId,event,headSha,status,conclusion,jobs,url

gh run view 30741650188 \
  --repo curoky/devspace \
  --json databaseId,event,headSha,status,conclusion,jobs,url
```

第二次主要 job：

```text
https://github.com/curoky/devspace/actions/runs/30741650188/job/91480045405
```

GitHub log 可以证明 build step 的错误和 platform 输出，但 runner-local pcap、socket
状态和 BuildKit history 不会自动上传到 GitHub。

### 14.3 外部 `bm` 源码复核

本文分析基于 `standalone-binaries@58b877e`。关键文件：

```text
cmd/binman/main.go
cmd/binman/registry.go
cmd/binman/install.go
cmd/binman/main_test.go
cmd/binman/install.sh
go.mod
```

需要检查的符号和调用：

```text
maxParallel
resolveArtifacts
downloadArtifacts
remoteLayer
remote.Image
remote.NewPuller
remote.Reuse
cmdOutdated
```

依赖版本：

```text
github.com/google/go-containerregistry v0.21.7
```

该依赖的 Puller 复用语义应以当前 pin 的源码为准，不应只依赖本文描述。

### 14.4 已丢失或未持久化的原始资产

以下资产位于 ephemeral runner 或本机 `/tmp`，没有提交到 `devspace`：

- 两次 tmate 的 session state。
- `/tmp/repro.Dockerfile` 等最小复现文件。
- 原始 pcap。
- runner 上的 BuildKit local history database。
- `old16/reuse16/reuse8/reuse4` 二进制。
- `/tmp/standalone-binaries` 中的未提交修复原型。

本文保留了它们产生的关键计数、hash、history ID 和结论边界，但不能替代原始 pcap。
下一轮正式 A/B 应把脚本、summary 和必要的 pcap 作为 Action artifact 上传，避免再次因
runner 销毁丢失证据。

### 14.5 下一位调查者的最短路径

如果需要继续当前调查，不必重复所有探索步骤。建议顺序：

1. 触发无 cache、开启 tmate 的 workflow。
2. 进入一个已复现的失败 matrix job。
3. 先保存 `docker buildx history inspect/logs` 和空闲 GHCR baseline。
4. 在独立 tmux window 启动 pcap 和 probe，避免主 shell 退出终止 session。
5. 从 `standalone-binaries@58b877e` 构建 `old16/reuse16/reuse8/reuse4`。
6. 先运行只 resolve 的交错 A/B，再运行完整 sync。
7. 上传实验脚本、CSV summary 和 pcap。
8. 根据第 13.4 节的标准决定是否需要降低 resolve 并发。
9. 把最终修复提交到 `standalone-binaries`，发布两个 Linux `bm` artifact。
10. 回到 `devspace` 跑完整无 cache matrix。
