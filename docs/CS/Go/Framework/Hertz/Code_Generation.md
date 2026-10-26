# Hertz Code Generation

## Introduction

`hz` 是 Hertz 的**官方代码生成工具**，定位与 Kitex 在 RPC 世界的角色相同：把「接口定义」作为单一事实来源，从 **Thrift（`.thrift`）** 或 **Protobuf（`.proto`）** IDL 直接产出可编译的 Hertz 项目骨架（handler、router、model、client）。这把「先写接口契约还是先写代码」的争论收口到 IDL——契约变了，`hz update` 增量补代码，不覆盖你已实现的 handler。

hz 与 Hertz 本体**独立发版**（GitHub Releases 形如 `cmd/hz/v0.9.8`），安装方式：`go install github.com/cloudwego/hertz/cmd/hz@latest`。

## Commands

hz 提供四个主命令（`cmd/hz/meta/const.go` 定义）：

| 命令 | 作用 |
| :-- | :-- |
| `hz new --idl api.thrift --module github.com/example/svc` | 从 IDL 脚手架出完整新项目（含 main、router、handler、model） |
| `hz update --idl api.thrift` | IDL 变更后增量补齐新增的 handler / 路由，**不覆盖**已有实现 |
| `hz model --idl api.thrift` | 仅根据 IDL 类型生成 Go 结构体（model） |
| `hz client --idl api.thrift --base_domain localhost:8888` | 根据 IDL 的 service 定义生成 Hertz HTTP 客户端代码 |

`module` 默认从项目根 `go.mod` 自动探测；`update` / `model` / `client` 都读 `go.mod` 拿 module 名，无需重复传。Thrift 需要 `thriftgo`（缺失时 hz 自动装），Protobuf 需要本机已装 `protoc`。

## Project Layout

`hz new` 生成的标准布局（定义在 `cmd/hz/generator/layout_tpl.go`）：

```
project/
├── main.go              # 应用入口，注册 router 与 handler
├── go.mod               # Go module 定义
├── .hz                  # hz 项目清单（update 时据此增量更新）
├── biz/
│   ├── handler/         # HTTP handler 实现（--handler_dir 可改）
│   ├── router/          # 路由注册（--router_dir 可改）
│   └── model/           # IDL 类型对应的 Go 结构体（--model_dir 可改）
├── script/
│   └── bootstrap.sh     # 启动脚本
└── build.sh             # 构建脚本
```

`.hz` 是 hz 的**项目清单**（manifest），记录上次生成时的 IDL 路径与配置，`hz update` 依赖它做增量比对——不要把 `.hz` 当临时文件删掉，否则 `update` 无法识别既有代码边界。

常用布局相关 flag：`--handler_dir` / `--model_dir` / `--router_dir` / `--client_dir` 改各目录位置；`--handler_by_method` 让「一个 method 一个文件」而非「一个 service 一个文件」；`--sort_router` 让路由注册顺序确定化（可复现输出）；`--force` 强制覆盖。

## IDL Annotations

Hertz 用 `api.*` 注解把 IDL 字段 / 方法映射到 HTTP 语义，用 `openapi.*` 注解补充文档信息：

| 注解 | 作用 |
| :-- | :-- |
| `api.get` / `api.post` / `api.put` / `api.delete` | 标记方法对应的 HTTP 动词 |
| `api.query` / `api.path` / `api.header` / `api.body` / `api.cookie` | 标记字段来自请求的哪一部分 |
| `api.base_domain` / `api.baseurl` | 生成客户端 / Swagger 时的基础地址 |
| `openapi.operation` / `openapi.schema` / `openapi.property` | 补充 OpenAPI 文档的文案与结构 |

```thrift
struct CreateUserReq {
    1: string name (api.query="name");
}

service UserService {
    CreateUserResp CreateUser(1: CreateUserReq req) (api.post="/api/users", api.body="req");
}
```

## Swagger / OpenAPI Generation

`hertz-contrib/swagger-generate` 提供两个插件（发布形态为 `protoc-gen-http-swagger` 与 `thrift-gen-http-swagger`），从带 `api.*` / `openapi.*` 注解的 IDL **编译期**产出：

- `openapi.yaml`：完整 OpenAPI 3.0 文档（Info / Paths / Components / Servers）。
- `swagger.go`：把 Swagger UI 绑定进 Hertz 服务的 Go 代码（`BindSwagger(h)` 注册 `/swagger/*` 路由）。

生成流程是**注解驱动**的：插件收到 protoc / thriftgo 解析出的描述符后，抽取注解构建文档，与服务端标准路由共用 Hertz 的路由与中间件机制，无需自定义 transport。

## Plugin Mode

hz 既能作为独立 CLI 跑，也能作为 `thriftgo` / `protoc` 的**插件**运行（通过 `HERTZ_PLUGIN_MODE` 环境变量识别）。在插件模式下，hz 跟随 IDL 编译器的调用时机生成代码，便于把 Hertz 代码生成嵌入既有的 IDL 构建流水线。

## Links

- [Hertz](/docs/CS/Go/Framework/Hertz.md)
- [Architecture](/docs/CS/Go/Framework/Hertz/Architecture.md)
- [Extensions](/docs/CS/Go/Framework/Hertz/Extensions.md)

## References

- <https://pkg.go.dev/github.com/cloudwego/hertz/cmd/hz>
- <https://github.com/cloudwego/hertz/tree/main/cmd/hz>
- <https://github.com/hertz-contrib/swagger-generate>
- <https://www.cloudwego.io/docs/hertz/opensource/toolkit/>
