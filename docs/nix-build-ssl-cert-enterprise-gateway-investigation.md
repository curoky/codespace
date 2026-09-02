<!-- markdownlint-disable MD013 -->

# nix build 下载失败（SSL 证书 / 企业 TLS 网关）排查

## 1. 文档状态

- 调查时间：2026-08-31
- 触发命令：`nix build .#ffmpeg`（仓库 `curoky/standalone-binaries`，aarch64-darwin）
- 涉及文件：`packages/ffmpeg/darwin.nix`、`/etc/nix/nix.conf`
- 涉及外部端点：`https://cache.nixos.org`、`http(s)://tarballs.nixos.org`
- 涉及组件：Nix 2.33.0（daemon 模式，multi-user 安装）、其内置 libcurl（OpenSSL 后端）
- 当前状态：根因已定位为企业 TLS 拦截网关（`SealSuite SWG`）重签证书，而 Nix 内置 OpenSSL 后端的信任库不含该企业根 CA；解决方向（把企业根并入 Nix 使用的 CA bundle 并写入 `nix.conf` 的 `ssl-cert-file`）已用客户端下载验证成功，尚未完成 daemon 落地后的完整 `nix build .#ffmpeg` 回归

本文记录完整排查过程，包括已验证事实、被排除方向、失败实验、根因边界与解决方案。文中不会把没有证据支持的推断写成确定结论。

## 2. 现象

`nix build .#ffmpeg` 最初报 Nix 求值错误，修复后进入下载阶段，卡在 stdenv bootstrap 的 fixed-output derivation `bootstrap-tools.tar.xz`，反复出现两类错误：

```text
warning: error: unable to download 'https://cache.nixos.org/nix-cache-info':
  SSL peer certificate or SSH remote key was not OK (60)
  SSL certificate problem: unable to get local issuer certificate

warning: error: unable to download
  'http://tarballs.nixos.org/stdenv/aarch64-apple-darwin/.../bootstrap-tools.tar.xz':
  HTTP error 301 (curl error: SSL peer certificate or SSH remote key was not OK)

warning: error: unable to download '.../bootstrap-tools.tar.xz': HTTP error 502
```

最终 `error: Build failed due to failed dependency`，不生成 `result`。

## 3. 两个独立问题

排查中确认存在两个**互相独立**的问题，必须分开处理：

| 问题 | 层面 | 状态 |
| --- | --- | --- |
| A. `darwin.nix` 求值报错 `expected a set but found a function` | 代码（Nix 语法） | 已修复 |
| B. 下载阶段 TLS 校验失败 / 502 | 环境（企业 TLS 网关 + Nix 证书信任） | 根因已定位，解决方案已验证下载成功 |

### 3.1 问题 A：`.bin` 属性选择的优先级 bug（已修复）

原始 `darwin.nix` 写法：

```nix
ffmpeg_static =
  (ffmpeg-headless.override { ... }).overrideAttrs (_: {
    doCheck = false;
  }).bin;
```

Nix 中属性选择 `.bin` 的结合优先级**高于**函数应用，因此 `overrideAttrs (_: {...}).bin` 被解析为 `overrideAttrs ((_: {...}).bin)`，即 `.bin` 作用在传给 `overrideAttrs` 的 lambda 上，而非 override 后的 derivation。报错：

```text
error: expected a set but found a function: «lambda @ .../darwin.nix:93:23»
```

`.override { ... }` 没触发是因为其实参是 set 字面量 `{...}` 而非 lambda。

修复：把整个 `overrideAttrs (_: {...})` 调用用括号包起来，让 `.bin` 作用在其结果上：

```nix
ffmpeg_static =
  (
    (ffmpeg-headless.override { ... }).overrideAttrs (_: {
      doCheck = false;
    })
  ).bin;
```

修复后求值通过，构建进入下载阶段。此问题与后续 TLS 问题无关。

### 3.2 问题 B：企业 TLS 网关重签 + Nix 信任库缺企业根（根因）

## 4. 已验证事实

以下均为命令直接产出的结论，非推断。

1. **证书 bundle 文件本身有效**。`/nix/var/nix/profiles/default/etc/ssl/certs/ca-bundle.crt`（`nss-cacert-3.115`）含 146 个 PEM 证书块；系统 `curl --cacert <该文件>` 访问 `cache.nixos.org` 返回 `200`；`openssl s_client -CAfile <该文件>` 返回 `Verify return code: 0 (ok)`。

2. **系统 `curl` 成功，Nix 内置下载器失败**。系统 `/usr/bin/curl` 是 SecureTransport（LibreSSL）后端，自动信任 macOS 系统钥匙串；Nix 2.33.0 内置下载器用 OpenSSL 后端的 libcurl（`nix-store` 依赖 `curl-8.14.1` + `openssl-3.4.3`），只认显式 CA 文件。

3. **Nix 确实读取了 `ssl-cert-file`，但用它验证仍失败**。用 `--option ssl-cert-file /tmp/nope.pem`（不存在）报 `error setting certificate file`（错误码 77），证明路径被读取；用真实标准 bundle 报 `unable to get local issuer certificate`（错误码 60），证明文件被加载但**证书链验证失败**。

4. **服务端证书是被企业网关重签的**。`openssl s_client -connect cache.nixos.org:443` 显示证书链根为 `SealSuite SWG Root CA - v1`，中间 CA 为 `SealSuite SWG Intermediate CA - v1`——这是企业 Secure Web Gateway 的 TLS 拦截，不是 nixos 官方证书链（本应是公共 CA）。

5. **标准 bundle 不含该企业根**。`nss-cacert` 只含公共 CA，因此 OpenSSL 后端找不到 `SealSuite` 这个 issuer，必然 `unable to get local issuer certificate`。系统 curl 之所以成功，是因为该企业根已被装入 macOS 系统钥匙串。

6. **把企业根并入 bundle 后，Nix 下载立即成功**。从系统钥匙串导出 `SealSuite` 证书（`security find-certificate -a -c SealSuite -p /Library/Keychains/System.keychain`，3 张）拼接到标准 bundle（合并后 149 张），指给 Nix 后成功：`Downloaded 'https://cache.nixos.org/nix-cache-info'`。

7. **`ssl-cert-file` 是 restricted setting**。非 trusted user 通过 `--option` 或环境变量设置会被忽略：`ignoring the client-specified setting 'ssl-cert-file', because it is a restricted setting and you are not a trusted user`。因此只有写入 `/etc/nix/nix.conf`（由 root daemon 读取）才对实际构建生效。

8. **502 是同一网关行为的一部分**。`http://tarballs.nixos.org/...` 直连时间歇返回 502；成功时 301 重定向到 https，随即触发上面的证书校验失败。二者交织表现为 `HTTP error 301 (curl error: SSL peer certificate ... not OK)`。

## 5. 被排除的方向

- **「删掉 `nix.conf` 里的 `ssl-cert-file` 行」**：反而使 daemon 失去 CA 文件，https 下载稳定失败。该行是必要配置，不该删。
- **命令行 `NIX_SSL_CERT_FILE` / `SSL_CERT_FILE` / `SSL_CERT_DIR` / `CURL_CA_BUNDLE`**：daemon 模式下下载由 root daemon 执行，客户端环境变量传不进 daemon；且 `ssl-cert-file` 为 restricted setting，客户端设置被忽略。
- **`sudo launchctl setenv NIX_SSL_CERT_FILE ...`**：被 SIP 拒绝（`Operation not permitted while System Integrity Protection is engaged`）。
- **本地 store 直连绕过 daemon（`--store 'local?root=/'`）**：需要 root，`opening lock file ".../big-lock": Permission denied`。
- **纯靠重试撞上 http 200**：上游 502 概率性成功（实测约 1/4），不可靠，且成功走 https 时仍会撞上证书问题。
- **怀疑 bundle 文件损坏或 Nix bug**：已排除。bundle 有效（事实 1），Nix 确实读取该文件（事实 3），根因是信任库缺企业根（事实 4/5/6）。

## 6. 根因

网络出口存在企业 TLS 拦截网关 `SealSuite SWG`，对 `cache.nixos.org`、`tarballs.nixos.org` 等 HTTPS 端点用私有根 CA `SealSuite SWG Root CA - v1` 重签证书。macOS 系统信任库（钥匙串）已包含该企业根，故系统 curl 及依赖 SecureTransport 的程序正常；但 Nix 2.33.0 内置 libcurl 使用 OpenSSL 后端，只信任 `ssl-cert-file` 指向的 CA bundle，而标准 `nss-cacert` bundle 不含该企业根，导致所有经 Nix 的 HTTPS 下载 `unable to get local issuer certificate`。间歇 502 与 301 重定向失败是同一网关行为的表象。

## 7. 解决方案

把企业根 CA 并入 Nix 使用的 CA bundle，并通过 `nix.conf` 的 `ssl-cert-file` 让 root daemon 使用（这是唯一对实际构建生效的入口）。放在持久位置而非只读 store 路径，避免随 GC / 更新失效。

```bash
# 1. 生成含企业根的合并 CA bundle 到持久位置
sudo mkdir -p /etc/nix/certs
security find-certificate -a -c "SealSuite" -p /Library/Keychains/System.keychain \
  | sudo tee /etc/nix/certs/enterprise-roots.pem >/dev/null
cat /nix/var/nix/profiles/default/etc/ssl/certs/ca-bundle.crt /etc/nix/certs/enterprise-roots.pem \
  | sudo tee /etc/nix/certs/ca-bundle.crt >/dev/null

# 2. 让 nix.conf 的 ssl-cert-file 指向合并 bundle
sudo sed -i '' '/^ssl-cert-file/d' /etc/nix/nix.conf
echo 'ssl-cert-file = /etc/nix/certs/ca-bundle.crt' | sudo tee -a /etc/nix/nix.conf

# 3. 重启 daemon
sudo launchctl kickstart -k system/org.nixos.nix-daemon
```

### 7.1 验证

```bash
# daemon 侧 TLS（应成功下载而非报证书错误）
nix store prefetch-file https://cache.nixos.org/nix-cache-info

# 完整构建
nix build .#ffmpeg
file result/bin/*
```

> 注意：`http://tarballs.nixos.org` 的间歇 502 属上游/网关波动，证书修复后仍可能需要重试；可加 `--option download-attempts 20` 降低敏感度。

## 8. 剩余验证

- [ ] daemon 落地合并 bundle 后，`nix store prefetch-file https://cache.nixos.org/nix-cache-info` 稳定成功。
- [ ] 完整 `nix build .#ffmpeg` 通过并生成 `result`，`file result/bin/*` 符合产物不变量。
- [ ] 确认企业根证书更换 / 轮换时的更新流程（`enterprise-roots.pem` 需重新导出）。

## 9. 排查命令速查

| 目的 | 命令 |
| --- | --- |
| 看服务端证书链根（识别是否被网关重签） | `echo \| openssl s_client -connect cache.nixos.org:443 2>/dev/null \| openssl x509 -noout -issuer` |
| 判断 bundle 是否有效 | `openssl s_client -connect cache.nixos.org:443 -CAfile <bundle>`（看 `Verify return code`） |
| 判断 Nix 是否读取了 `ssl-cert-file` | `nix store prefetch-file <url> --option ssl-cert-file /tmp/nope.pem`（报 error 77 = 已读取） |
| 从系统钥匙串导出企业根 | `security find-certificate -a -c "SealSuite" -p /Library/Keychains/System.keychain` |
| 查看 daemon 是否 daemon 模式 | `ps aux \| grep nix-daemon`；`nix config show store` |
| 查看 Nix 内置 curl 的 SSL 后端 | 经 `nix-store -q --references` 定位 `nix-store` 依赖的 `curl` / `openssl` |
