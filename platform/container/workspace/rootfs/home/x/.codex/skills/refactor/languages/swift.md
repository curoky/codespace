# Swift 重构参考（详细·确定性）

> 写/改/重构/评审 Swift,或起步(0→1)选型时加载。本文件是 Swift 的完整规范:起步基线(§0)+「旧惯用法 → 现代惯用法」改写映射 + 风格/类型/错误/并发/测试/安全/库选型条件/语言构造选择/工具链。冲突时以 `../SKILL.md` 的重构判据为准。搭建新项目/工程治理时，本文件也是 `project-setup` skill 引用的语言选型与工具链唯一真相。

## 0. 基线

- **版本**:官方最新稳定 Swift,启用 Swift 6 language mode 与 strict concurrency `complete`(落地核实);`.swift-version` 锁定具体稳定版。
- **包/构建**:`SwiftPM`,`Package.swift` 声明与 toolchain 匹配的 `swift-tools-version` 与真实目标平台,leaf 项目提交 `Package.resolved`。
- 标准库/Foundation 够用时不引三方(`Codable`、`URLSession`、`swift-collections`);优先 swiftlang/swift-server/Apple/Point-Free 生态。

## 现代化改写映射（旧 → 新）

- 强制解包 `!`、隐式解包可选 → `guard let`/`if let`（简写解包）、`??` 默认值。
- `as!` 强制转型 → `as?` + 分支处理或 `guard`。
- completion handler / 回调 → `async`/`await` + 结构化并发；桥接旧 API 用 `withCheckedContinuation`/`withCheckedThrowingContinuation`。
- `class` + 手动锁保护共享可变状态 → `actor` 隔离。
- `ObservableObject`/`@Published` → `@Observable` 宏 + `@State`/`@Bindable`。
- `Foundation.Process` → async-native `swift-subprocess` 的 `run(_:arguments:)`。
- Core Data 新项目 → `SwiftData`；`grpc-swift` v1 → `grpc-swift-2`。
- 未类型化 `throws` → typed `throws`（Swift 6.0）约束错误类型。
- `Array` 定长热点 → `InlineArray`（`[N of T]`）。
- `Any`/`AnyObject` → 泛型、`protocol`、`some`（opaque）/`any`（existential）。

## Approachable Concurrency 接线（Swift 6 迁移要点）

- SPM 无单一开关，需在 target `swiftSettings` 显式接线：
  - UI/可执行 target 配 `.defaultIsolation(MainActor.self)`，默认单线程主 actor 隔离，减少 `@MainActor` 标注；这是独立旋钮，与下面的 upcoming feature 分开。
  - 已用 `swiftLanguageModes: [.v6]` 时，再开尚未随 v6 默认启用的 upcoming feature：`.enableUpcomingFeature("NonisolatedNonsendingByDefault")`（SE-0461，`nonisolated async` 继承调用方上下文）与 `.enableUpcomingFeature("InferIsolatedConformances")`（SE-0470）。
- 需要真正并行、脱离当前 actor 到并发线程池的部分，显式标 `@concurrent`；否则 `async` 默认留在调用方上下文，避免无谓的 actor 跳变。
- 开启 opt-in strict memory safety 标记不安全构造。

## 1. 风格与模块

- 命名：类型/协议 `UpperCamelCase`，变量/函数/枚举 case/全局常量 `lowerCamelCase`；布尔用 `is`/`has`/`should` 前缀；缩写统一如 `URL`、`id`。
- 遵循 Swift API Design Guidelines：调用点读起来像句子，参数标签清晰，省略冗余词。
- 魔法值提取为 `static let` 常量或 `enum`；格式交给 `swift-format` 或 `SwiftFormat`。
- 函数超过一屏、出现阶段性注释、或名称需用 `and` 描述时拆分。
- 参数超过 3 个用配置 `struct`；避免布尔陷阱参数，改用 `enum`。
- 访问控制显式：默认 `internal`，公共 API 用 `public`/`package`，实现细节 `private`/`fileprivate`；用 `extension` 组织 protocol conformance。
- 高层逻辑依赖 `protocol` 并由外部注入实现；避免单例全局可变状态和循环依赖。

## 2. 类型、错误、资源

- 避免 `Any`/`AnyObject`；用泛型、`protocol`、`some`（opaque）/`any`（existential）表达。
- 外部输入用 `Codable` 解码后校验并转为领域类型；边界做范围/有效性检查。
- 互斥状态用带关联值的 `enum` + `switch` 穷尽匹配；可能缺失写成 `T?` 并就近 `guard let`/`if let` 解包。
- 可预期失败用 `throws` + 具体 `Error` 类型或 `Result<T, E>`；typed `throws`（Swift 6.0）约束错误类型；真正不可恢复才 `fatalError`/`precondition`。
- 错误类型定义为遵从 `Error`/`LocalizedError` 的 `enum`；`do`/`catch` 捕获具体错误，不吞错、不只打印后继续。
- 资源释放用 `defer`；`class` 生命周期用 `deinit`；打破循环引用用 `weak`/`unowned`（`[weak self]`）。
- 独占资源（文件句柄、锁、连接）可用 `~Copyable` 值类型 + `deinit` 表达唯一所有权，配 `consuming`/`borrowing` 精确控制所有权转移，零拷贝且离开作用域自动释放；仅在确有独占语义或性能诉求时用，别为普通值类型强加。

## 3. 并发

- 用当前 Swift 的 Approachable Concurrency（SPM 无单一开关，需在 target `swiftSettings` 显式接线）：
  - UI/可执行 target 配 `.defaultIsolation(MainActor.self)`，默认单线程主 actor 隔离，减少 `@MainActor` 标注；这是独立旋钮，与下面的 upcoming feature 分开。
  - 已用 `swiftLanguageModes: [.v6]` 时，再开尚未随 v6 默认启用的 upcoming feature：`.enableUpcomingFeature("NonisolatedNonsendingByDefault")`（SE-0461，`nonisolated async` 继承调用方上下文）与 `.enableUpcomingFeature("InferIsolatedConformances")`（SE-0470）。
- 需要真正并行、脱离当前 actor 到并发线程池的部分，显式标 `@concurrent`；否则 `async` 默认留在调用方上下文，避免无谓的 actor 跳变。
- 统一 `async`/`await` + 结构化并发；不混用回调/completion handler（桥接旧 API 用 `withCheckedContinuation`/`withCheckedThrowingContinuation`）。
- 共享可变状态用 `actor` 隔离；跨隔离域传值必须 `Sendable`，`@Sendable` 闭包禁止捕获可变引用。
- 独立任务用 `async let` 或 `TaskGroup`（`withTaskGroup`/`withThrowingTaskGroup`）；批量并发用分块或信号量限流。
- Task 取消协作式检查 `Task.isCancelled` / `try Task.checkCancellation()`；长任务配超时。
- 异步代码中不做阻塞 I/O；CPU 密集放后台不占用协作线程池。
- 流式数据用 `AsyncSequence`/`AsyncStream`，补充能力用 `swift-async-algorithms`；用 `-strict-concurrency=complete` 编译期检测竞态。

## 4. 注释与测试

- 注释写意图、约束、权衡、坑；不复述代码。公共 API 用 `///` 文档注释（Swift-DocC 风格），说明参数、返回、`throws`。
- 改代码同步改注释；删死代码；`TODO`/`FIXME`/`HACK` 附负责人或 issue。
- 测试默认 Swift Testing（`@Test`、`#expect`、`#require`、`arguments` 参数化）；维护存量或需 XCTest 专有能力（性能/UI 测试）时用 XCTest。
- 测公共行为和边界，不测私有实现；外部依赖用 `protocol` + fake/mock，时间用可注入时钟。
- 修 bug 先写复现用例；覆盖率是参考，不是目标。

## 5. 安全与日志

- 外部输入用 `Codable` + 校验后再进内部类型；按输出上下文转义。
- SQL 用参数化占位符（`GRDB`/`PostgresNIO`）；禁止拼接 SQL。子进程用 async-native `swift-subprocess` 的 `run(_:arguments:)`（参数数组），不经 shell 拼接、不再用冗长的 `Foundation.Process`。
- 加密用 `CryptoKit`（macOS 原生）；随机数/令牌用 `SystemRandomNumberGenerator` 或 CSPRNG，不自行拼凑；密钥用 Keychain，不硬编码。
- 密码哈希用 `argon2`/`bcrypt`；不自行实现加密原语。
- 日志用 `swift-log`（`Logger`）结构化输出；`print` 只作临时调试，提交前清理。
- 级别 `trace`/`debug`/`info`/`notice`/`warning`/`error`/`critical`；生产默认 `info`，日志带请求 ID、用户 ID、模块名等 metadata。
- 热路径避免高频日志；错误日志带原始错误；禁止记录口令、令牌、隐私数据。

## 6. 库选型

- 标准库/Foundation 够用时不引第三方；先确认 `Codable`、`URLSession`、`swift-collections`、`Foundation` 是否够用。
- 优先 swiftlang / swift-server / Apple / Point-Free 等主流生态。

| 场景 | 默认 | 条件 |
| --- | --- | --- |
| 包管理/构建 | `SwiftPM` | 必须；`Package.swift` 声明真实目标平台，leaf 项目提交 `Package.resolved`；大型多 target/多模块 Apple 工程按需配 `Tuist`。 |
| CLI 参数 | `swift-argument-parser` | 必须。 |
| 日志 | `swift-log` | 必须；结构化 `Logger`。 |
| JSON | 标准库 `Codable` | 必须；`JSONEncoder`/`JSONDecoder`。 |
| HTTP 服务 | `Vapor` / `Hummingbird` | 全功能生态用 Vapor 4；轻量/可组合用 Hummingbird 2。 |
| HTTP 客户端 | `URLSession` / `async-http-client` | macOS 客户端默认 `URLSession`（async/await）；服务端高吞吐用 `async-http-client`。 |
| 子进程 | `swift-subprocess` | 必须；async-native，替代 `Foundation.Process`。 |
| 底层网络 | `SwiftNIO` | 按需；高性能异步 I/O 基座。 |
| SQLite | `GRDB` | 嵌入式 SQLite。 |
| PostgreSQL | `PostgresNIO` | 服务端；Vapor 全栈用 `Fluent`。 |
| Apple 端持久化 | `SwiftData` | 新项目默认；存量用 Core Data。 |
| 加密 | `CryptoKit` | macOS 原生默认；确需跨平台移植时用 `swift-crypto`（API 一致）。 |
| 集合扩展 | `swift-collections` | 按需；`Deque`/`OrderedSet`/`Heap`。 |
| 算法 | `swift-algorithms` | 按需。 |
| 数值 | `swift-numerics` | 按需。 |
| 异步序列 | `swift-async-algorithms` | 按需；`AsyncSequence` 补充。 |
| 依赖注入 | 手动注入 / `swift-dependencies` | 小中型手动；需统一注册/覆盖用 `swift-dependencies`。 |
| Redis | `RediStack` | 按需。 |
| gRPC | `grpc-swift-2` | 必须；新项目用当前 v2；`grpc-swift` v1 仅存量维护。 |
| macOS 端 UI | `SwiftUI` + `Observation` | 新界面默认；状态用 `@Observable` 宏（配 `@State`/`@Bindable`），不用 `ObservableObject`；需要 SwiftUI 未覆盖的能力时下沉 AppKit。 |
| 测试 | `swift-testing` | 必须；XCTest 用于存量与专有能力。 |
| Lint | `SwiftLint` | 必须；配置 `.swiftlint.yml`。 |
| 格式化 | `swift-format` / `SwiftFormat` | 二选一；官方工具链一致性优先 `swift-format`。 |

## 7. 语言构造选择

- `struct` vs `class`: 默认 `struct` 值语义；需引用语义、身份标识、继承或 `deinit` 才用 `class`。
- `Copyable` vs `~Copyable`: 默认可复制值类型；仅当需唯一所有权（独占资源、带 `deinit` 的 struct、Swift-native 锁/原子）或杜绝隐式拷贝的性能诉求时才用 `~Copyable` + `consuming`/`borrowing`；其「不可复制」会传染到含它的类型，别为普通模型强加。
- `some` vs `any`: 编译期单一具体类型用 `some`（opaque，零开销）；运行时异构存储用 `any`（existential，有开销）。
- `Array` vs `InlineArray`: 默认 `Array`；编译期已知固定长度、性能敏感（解析/音视频/游戏循环）用 `InlineArray`（`[N of T]`，栈上、无堆分配）。

## 8. 工具链

| 用途 | 工具 |
| --- | --- |
| 包/依赖/版本 | `SwiftPM`，`Package.swift` 声明与 toolchain 匹配的 `swift-tools-version` 与真实目标平台；`.swift-version` 锁定具体稳定版；leaf 项目提交 `Package.resolved`；`swift build`/`swift run`。 |
| 格式化 | `swift-format` / `SwiftFormat`。 |
| Lint | `SwiftLint`，配置 `.swiftlint.yml`。 |
| 测试/覆盖率 | `swift test --enable-code-coverage`；`swift-testing`。 |
| 构建 | `swift build`（发布配 `-c release`）；带 Apple UI/资源的 app 用匹配当前 Swift toolchain 的 Xcode `xcodebuild`。 |

- pre-commit 用 `lefthook` 对暂存 `*.swift` 跑 `swift-format`/`SwiftFormat` 与 `SwiftLint`；CI 对全项目重复格式/Lint，并运行 `swift build`、`swift test`。
