## Introduction

TypeScript 生态里最著名的配置陷阱不是严格模式，而是**两套互不兼容的装饰器实现共用一个 `@` 语法**：一套是 TS 早期的实验实现（`experimentalDecorators`），Angular、NestJS、TypeORM 全建在它上面；另一套是 TC39 Stage 3 标准装饰器，TS 5.0 起默认启用。选错不是风格问题——它直接决定 NestJS 的依赖注入能不能工作。本篇讲清两套系统的差异、元数据发射的机制，以及 TS 7 时代的迁移现实。

## Two Systems, One Syntax

| 维度 | Legacy（`experimentalDecorators: true`） | Stage 3 标准（TS 5.0+ 默认） |
|------|----------------------------------------|------------------------------|
| 方法装饰器签名 | `(target, propertyKey, descriptor)` | `(value, context)` |
| 字段装饰器 | `(target, propertyKey)` | 收到 `undefined`，返回 initializer |
| 参数装饰器 | 支持 | **不支持**（独立提案，未合入） |
| 元数据 | `emitDecoratorMetadata` + `reflect-metadata` | `Symbol.metadata`，**不发射参数类型** |
| 改变成员种类 | 可以（更宽松） | 替换必须同种类 |
| 类型安全 | 签名弱（`any` / `string`） | 按 `context.kind` 精确分型 |
| 引擎原生 | 无 | 无（2026 年中 V8 未实现；Deno 已支持） |
| 代表用户 | Angular / NestJS / TypeORM / MikroORM / InversifyJS / class-validator | Lit / MobX / Effect 等新库 |

两把开关互斥：`experimentalDecorators: true` 时 TS 走 legacy 语义，标准语义被完全忽略。一个 tsconfig 里两者不能共存，**框架绑定你的选择**，不是团队偏好。

## Legacy Mode in Detail

legacy 模式下编译器把装饰器降级成 `__decorate` / `__metadata` 辅助调用：

```typescript
// 源码
@Controller("/user")
class UserController {
  constructor(private readonly userService: UserService) {}
}

// 编译产物（示意）
__decorate(
  [Controller("/user"), __metadata("design:paramtypes", [UserService])],
  UserController
)
```

行为要点：

- **求值顺序**：参数装饰器 → 方法/访问器装饰器 → 字段装饰器 → 类装饰器；同一种类的多个装饰器**从后往前**求值；
- **参数属性** `constructor(private readonly x: number)` 会生成赋值语句，属于"擦不掉的语法"，与 `erasableSyntaxOnly` 直接冲突；
- 装饰器签名里 `target` 是 `any`、`propertyKey` 是 `string`，写错装饰目标编译器不拦——类型安全是 Stage 3 的主要改进动机之一；
- `emitDecoratorMetadata` 必须配 `reflect-metadata` polyfill（`import "reflect-metadata"`），发射 `design:type` / `design:paramtypes` / `design:returntype` 三种键。

## Standard Stage 3 in Detail

标准装饰器给每个装饰器传 `(value, context)`，`context` 描述被装饰的元素：

```typescript
function logged(
  target: (this: unknown, ...args: unknown[]) => unknown,
  context: ClassMethodDecoratorContext,
) {
  const name = String(context.name)
  return function (this: unknown, ...args: unknown[]) {
    console.log(`calling ${name}`)
    return target.apply(this, args)
  }
}
```

`context` 的成员：`kind`（`"class"` / `"method"` / `"field"` / `"accessor"` / `"getter"` / `"setter"`）、`name`、`static`、`private`、`access`（含 `#` 私有名访问句柄）、`addInitializer`（注册实例化时执行的初始化函数）。

标准版引入 **`accessor` 关键字**创建自动访问器（getter/setter 对），这是装饰器能包装字段读写的关键——MobX 等库从 `@observable` 迁到标准装饰器必须改用 `@observable accessor`。

## emitDecoratorMetadata and the DI Ecosystem

这一节是整套 legacy 系统**真正无法迁移**的原因。NestJS、Angular、TypeORM、InversifyJS 的依赖注入这样工作：

```typescript
@Injectable()
class UserService {
  constructor(private readonly db: Database) {}   // 不需要任何显式 token
}
```

容器启动时读 `Reflect.getMetadata("design:paramtypes", UserService)`，拿到 `[Database]`，据此实例化并注入。**类型信息在编译后被擦除，是 `emitDecoratorMetadata` 把它反射回了运行时。**

Stage 3 装饰器刻意不包含这个能力：标准提案只暴露结构，不自动发射类型。所以绑死在这套机制上的框架没有"打开标准装饰器"的迁移路径，社区给出的方向是换一种元数据来源：

- **显式注入 token**（`@Inject("Database")`），把类型推断改成显式声明——NestJS 已长期支持；
- **编译期元数据发射器**：直接从类型注解（而非装饰器）生成 `Reflect.defineMetadata` 调用，复用同一套 `design:*` 键与 `reflect-metadata` 运行时，如 InversifyJS 生态的 `rflct` 项目；
- **等待 `Symbol.metadata` 生态成熟**——它解决的是"附加元数据"，不是"反射参数类型"，短期替代不了 `emitDecoratorMetadata`。

## Status in the 7.x Line

截至 2026 年 10 月的事实：

- TS 官方口径是 `experimentalDecorators` **保留到可预见的未来**（"for the foreseeable future"），7.0 没有移除它，legacy 代码可以继续编译；
- 7.0 的已知阻塞在**编程式 API**（7.1 稳定化），不在装饰器本身；`emitDecoratorMetadata` 走编译器 emit 路径，是 7.1 之后值得盯的观察项；
- 社区声称"TS 7 预期完全移除实验装饰器"的说法目前**没有官方时间表**，按"保留"做规划、按"可能变"留后路。

验证迁移是否安全的方法不是读发布说明，而是**跑测试**：同一份装饰器代码在 TS 6 与 TS 7 下的 metadata emit 应该等价，`--noEmit` 绿不能证明 emit 等价——启动应用、跑 DI 集成测试才是证据。

对新项目的建议：不绑 NestJS / TypeORM / Angular 就用标准装饰器（TS 5.0+ 默认，无需 flag）；绑了就保持 legacy，并在 7.x 过渡期把 typescript 6 以 alias 形式留住。

## Links

- [TypeScript 编译器](/docs/CS/TypeScript/Compiler.md)
- [TypeScript](/docs/CS/TypeScript/TypeScript.md)
- [tsconfig 工程配置](/docs/CS/TypeScript/Tsconfig.md)
- [TypeScript 工具链](/docs/CS/TypeScript/Toolchain.md)
- [TypeScript 类型系统](/docs/CS/TypeScript/TypeSystem.md)
- [Nodejs](/docs/CS/front-end/Nodejs.md)

## References

- [TC39 Decorators Proposal](https://github.com/tc39/proposal-decorators)
- [TypeScript Handbook: Decorators](https://www.typescriptlang.org/docs/handbook/decorators.html)
- [Announcing TypeScript 5.0 (Decorators)](https://devblogs.microsoft.com/typescript/announcing-typescript-5-0/)
- [reflect-metadata](https://github.com/rbuckton/reflect-metadata)
- [Decorator Metadata Proposal](https://github.com/tc39/proposal-decorator-metadata)
- [NestJS: Custom providers](https://docs.nestjs.com/fundamentals/custom-providers)
