# Go 重构参考（详细·确定性）

> 写/改/重构/评审 Go,或起步(0→1)选型时加载。本文件是 Go 的完整规范:起步基线(§0)+「旧惯用法 → 现代惯用法」改写映射 + 风格/类型/错误/并发/测试/安全/库选型条件/工具链。冲突时以 `../SKILL.md` 的重构判据为准。搭建新项目/工程治理时，本文件也是 `project-setup` skill 引用的语言选型与工具链唯一真相。

## 0. 基线

- 必用 Go Modules;新项目用官方最新稳定 Go(落地核实),`go.mod` 的 `go` 指令声明该稳定版、`toolchain` 锁定其最新 patch。
- 标准库优先(`net/http`、`encoding/json`、`log/slog`、`slices`/`maps`、`cmp`、`errors`、`context`、`time`),够用不引三方。
- 现代语法/标准库优先:泛型、`slices`/`maps`/`cmp`、`min`/`max` 内建、`for range n`、`errors.Is`/`As` + `fmt.Errorf("...: %w", err)`、`log/slog`;用 `go fix` modernizers 升级旧惯用法,可读性优先。

## 现代化改写映射（旧 → 新）

- `ioutil.ReadFile`/`ReadAll`/`WriteFile` → `os`/`io` 对应函数。
- 手写 min/max/包含/排序循环 → `min`/`max` 内建、`slices`、`maps`、`cmp`。
- `for i := 0; i < n; i++`（仅计数） → `for range n`。
- `golang.org/x/exp/slices`、`golang.org/x/exp/maps` → 标准库 `slices`/`maps`。
- `github.com/pkg/errors` 的 `Wrap`/`Cause` → `fmt.Errorf("...: %w", err)` + `errors.Is/As`。
- 手写 log 前缀/字段拼接 → `log/slog` 结构化键值。
- `golang/mock`（已归档） → `uber-go/mock`。
- `google/wire`（已归档）新项目 → 手动构造函数注入。
- `lib/pq` → `pgx`。
- 用 `go fix` modernizers 批量升级旧惯用法后人工复核。

## 1. 风格与模块

- 标识符用 `MixedCaps`/`mixedCaps`；导出靠首字母大小写；包名短小写，避免 `util`/`common`；缩写统一如 `HTTPServer`、`userID`。
- 布尔用 `is`/`has` 前缀；魔法值提取为 `const` 块和 `iota`。
- 格式用 `gofmt` + `goimports`。
- 函数超过一屏、出现阶段性注释、或名称需用 `and` 描述时拆分。
- 参数超过 3 个用 config struct 或 functional options；避免布尔陷阱参数。
- 公共 API 靠导出控制；`internal/` 限制可见性。
- 在使用方定义小接口，由实现方隐式满足，外部注入实现；尽早分层避免循环依赖。

## 2. 类型、错误、资源

- 避免空 `interface{}`/`any`；仅在边界且无法静态描述时局部使用并注明原因。
- 外部输入用 `go-playground/validator` 或显式校验后转为内部类型。
- 非法状态用具名类型、`const`/`iota` 枚举、小接口约束。
- 可能缺失用 `(T, bool)`、`(T, error)` 或指针表达；注意 nil 解引用。
- 可预期失败以最后一个返回值 `error` 表达；定义哨兵错误或自定义 error 类型；`panic` 只用于不可恢复错误。
- 禁止忽略 `error`；`_ = fn()` 必须有理由并注明；禁止空 `if err != nil {}`。
- 包装错误用 `%w`，判别用 `errors.Is/As`；资源释放用 `defer`。

## 3. 并发

- goroutine 必须有退出条件；不留泄漏 goroutine。
- 独立任务用 `errgroup`；批量并发用带缓冲 channel 信号量或 `errgroup.SetLimit`。
- `context.Context` 贯穿调用链，用 `WithCancel`/`WithTimeout` 支持取消与超时。
- goroutine 内 panic 要 recover 并上报。
- 共享状态优先通过 channel 协调；必要时用 `sync.Mutex`；用 `go test -race` 检测竞态。
- 性能确认用 `go test -bench` 和 `pprof`；需要时预分配切片、复用对象。

## 4. 注释与测试

- 注释写意图、约束、权衡、坑；不复述代码。导出标识符用 doc 注释，紧贴声明并以标识符名开头。
- 改代码同步改注释；删死代码；`TODO`/`FIXME`/`HACK` 附负责人或 issue。
- 测试用标准库 `testing`，表驱动 + `t.Run`。
- 测公共行为和边界，不测私有实现；外部依赖用接口 + `uber-go/mock` 或手写 fake。
- 可并行测试用 `t.Parallel()`；CI 跑 `-race`；修 bug 先写复现用例。

## 5. 安全与日志

- HTML 输出用 `html/template`，不用 `text/template`。
- SQL 用 `database/sql` 占位符 + `sqlc`；禁止拼接 SQL。
- 子进程用 `exec.Command(name, args...)`，不经 shell。
- 密码用 `argon2`/`bcrypt`；随机数用 `crypto/rand`，不用 `math/rand`。
- 日志用标准库 `log/slog` 结构化输出；`fmt.Println` 只作临时调试，提交前清理。
- 级别：`debug`/`info`/`warn`/`error`；生产默认 `info`。日志字段用 `slog` 键值属性。
- 热路径避免高频 `info`；错误日志带原始错误；禁止记录口令、令牌、隐私数据。

## 6. 库选型

- 标准库优先；先确认 `net/http`、`encoding/json`、`log/slog`、`slices`、`maps`、`errors`、`context` 是否够用。
- 避免停更/被取代库，如 `github.com/pkg/errors`。

| 场景 | 默认 | 条件 |
| --- | --- | --- |
| HTTP 服务/路由 | 标准库 `net/http` | 简单服务直接用；中间件/分组路由用 `chi`；重生态再看 `echo`/`gin`。 |
| 日志 | 标准库 `log/slog` | 日志是确认性能热点时再看 `zap`。 |
| 错误处理 | 标准库 `errors` | `errors.Is/As` + `%w`。 |
| 切片/映射 | 标准库 `slices` / `maps` | 替代手写循环和 `golang.org/x/exp/*`。 |
| CLI | 标准库 `flag` / `cobra` | 单层参数用 `flag`；复杂多级子命令用 `cobra`。 |
| 配置 | `caarlos0/env` / `viper` | 纯环境变量用 `caarlos0/env`；多来源/热加载/多格式用 `viper`。 |
| 校验 | `go-playground/validator` | 必须；struct tag 校验外部输入。 |
| SQL | `sqlc` / `sqlx` / `gorm` | 默认 `sqlc`；轻量增强用 `sqlx`；全功能 ORM 才用 `gorm`。 |
| 迁移 | `golang-migrate` | 必须。 |
| 并发组 | `errgroup` | 需首错取消和统一等待用；简单等待用 `sync.WaitGroup`。 |
| 测试断言 | 标准库 `testing` / `testify` | 核心逻辑优先标准库表驱动 + `t.Run`；断言样板多时用 `require/assert`，避免 `testify/suite` 掩盖结构。 |
| Mock | `uber-go/mock` | 按需；替代已归档 `golang/mock`。 |
| HTTP 重试 | 标准库 `net/http` + `go-retryablehttp` | 需退避重试时用。 |
| UUID | `google/uuid` | 按需。 |
| DI | 手动注入 | 构造函数/工厂显式组装；`google/wire` 已归档，仅存量项目维持或迁移。 |
| Lint | `golangci-lint` | 必须；v2.x。 |
| 漏洞扫描 | `govulncheck` | 必须。 |
| PostgreSQL | `pgx` | 必须；不新选 `lib/pq`。 |
| Redis | `redis/go-redis` | 按需。 |
| Kafka | `twmb/franz-go` / `segmentio/kafka-go` | 纯 Go 优先 `franz-go`；生态兼容需求用 `kafka-go`。 |
| 限流 | `x/time/rate` | 标准库扩展；令牌桶。 |
| 进度条 | `progressbar` / `mpb` | 单条用 `progressbar`；多条并发/装饰器用 `mpb`。 |
| gRPC | `grpc-go` | 必须；配 `protoc-gen-go`。 |
| 时间 | 标准库 `time` | 测试中注入时钟。 |

## 7. 工具链

| 用途 | 工具 |
| --- | --- |
| 依赖/版本 | `go mod` + `toolchain`，提交 `go.mod`、`go.sum`；用 `go mod tidy`。开发工具用 `tool` directive（`go get -tool` / `go tool`）锁入 `go.mod`。 |
| 格式化 | `gofmt` / `goimports`。 |
| Lint | `golangci-lint` v2.x，配置 `.golangci.yml`。 |
| 静态检查 | `go vet` / `staticcheck`。 |
| 测试 | `go test -race -cover ./...`。 |
| 漏洞扫描 | `govulncheck ./...`。 |
| 构建 | `go build`；交叉编译用 `GOOS`/`GOARCH`；发布可配 `goreleaser`。 |

- pre-commit 用 `lefthook` 对暂存 Go 文件跑 `gofmt`/`goimports` 校验；CI 跑全项目 `go vet`、`staticcheck`、`golangci-lint run`、`go test -race -cover ./...` 与 `govulncheck ./...`。
