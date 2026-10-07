## Introduction

TypeScript 的类型系统有几个反直觉的设计：**它是结构化的**（不看你叫什么，只看你长什么样）、**它是不健全的**（unsound，有一些故意留的洞）、**它的类型层是一门图灵完备的迷你语言**（所以才有所谓的"类型体操"）。这三点解释了日常写 TS 遇到的大部分"为什么这样也行"和"为什么这样不行"。

对应的四条主干能力：结构化子类型、控制流收窄、泛型与变型、类型层面的计算。

## Structural Types vs Nominal Types

TS 判断兼容性靠**结构**：成员对得上就兼容，不需要显式 `implements`。

```typescript
class User { constructor(public id: number) {} }
function printId(u: { id: number }) { console.log(u.id) }

printId(new User(1))          // OK
printId({ id: 1 })            // OK，字面量也对得上
printId({ id: 1, name: "a" }) // OK，多余属性在非字面量场景被容忍
```

这与 Java、C# 的名义子类型相反。收益很明显：给第三方库的鸭子类型加类型时不需要改它的源码。代价是**无法区分结构相同但语义不同的类型**，比如两个都是 `string` 的 `UserId` 和 `OrderId`：

```typescript
type UserId  = string
type OrderId = string

let u: UserId = "u-1"
let o: OrderId = "o-1"
u = o            // 完全合法，但语义上是 bug
```

绕过办法是 **branding**，用交叉类型人为引入一个不存在的字段做的图腾：

```typescript
declare const brand: unique symbol

type UserId  = string & { readonly [brand]: "UserId" }
type OrderId = string & { readonly [brand]: "OrderId" }

const asUserId = (s: string) => s as UserId

let u: UserId = asUserId("u-1")
let o: OrderId = "o-1" as OrderId
// u = o        // Error: Type 'OrderId' is not assignable to type 'UserId'
```

注意 brand 字段声明用 `declare const brand: unique symbol`，它不产生任何运行时代码，纯粹是给类型检查器看的一枚"戳"。

| 对比维度 | 结构化（TS） | 名义（Java / Go 的 interface 部分方向不同） |
|----------|-------------|--------------------------------|
| 谁说了能赋值 | 成员兼容即可 | 必须显式声明关系 |
| 对第三方鸭子类型 | 友好 | 需要适配器层 |
| 语义不同的同构类型 | 需要用 branding 人造区分 | 天然区分 |
| 误判方向 | **漏报**（该报的不报） | **误报**（可以用却不让用） |

TS 选结构化 + 容忍漏报，符合它"渐进采用、不打断现有 JS"的定位。

## Control Flow Analysis (CFA) and Type Narrowing

TS 里变量的类型不是静态标注，**而是随控制流变化**的。这是贯穿整个检查器的核心机制，也是 TS 比"只是加类型注释"强的地方。

```typescript
function print(x: string | number | null) {
  // x: string | number | null
  if (x === null) return
  // x: string | number
  if (typeof x === "string") {
    // x: string
    console.log(x.toUpperCase())
  } else {
    // x: number
    console.log(x.toFixed(2))
  }
}
```

可用的收窄手段，按常用程度排：

| 手段 | 写法 | 适用场景 |
|------|------|----------|
| `typeof` | `typeof x === "string"` | 基础类型分支 |
| 真值收窄 | `if (x)` | 顺带排掉 `null`/`undefined`/`""`/`0`——注意会误伤合法的 `0` 和空串 |
| `in` | `"swim" in animal` | 判别联合的替代写法 |
| `instanceof` | `x instanceof Date` | 类实例 |
| 判别联合 | `switch (msg.kind)` | **最推荐**的多态建模方式 |
| 类型谓词 | `function isUser(u: unknown): u is User` | 把收窄逻辑封装复用 |
| 断言函数 | `function assert(v: unknown): asserts v is User` | 收窄失败就 throw |

**判别联合（discriminated union）**是 TS 里替代继承建模的主力：

```typescript
type Shape =
  | { kind: "circle"; radius: number }
  | { kind: "square"; side: number }

function area(s: Shape): number {
  switch (s.kind) {
    case "circle": return Math.PI * s.radius ** 2   // s 收窄为 circle 分支
    case "square": return s.side ** 2
    default: {
      const _exhaustive: never = s                   // 漏了一个分支这里就报错
      throw new Error(`unknown shape: ${_exhaustive}`)
    }
  }
}
```

`never` 兜底那一行是 TS 的招牌技巧：**穷尽性检查**。往 `Shape` 里加一个分支但不改 `area`，`s` 在那个 default 里无法被收窄到 `never`，赋值就报错。这也是 TS 里少有的"编译器逼你修所有调用点"的手段。

类型谓词背后的含义要记牢——**谓词是你向编译器作的承诺，编译器不校验它**：

```typescript
function isString(x: unknown): x is string {
  return typeof x === "string"   // 这里写错成 "number"，编译器不会拦你
}
```

## Generics and Variance

写这行代码时的直觉差异来自变型规则：

```typescript
type A = (x: string | number) => void
type B = (x: string) => void

let a: A = (x) => {}
let b: B = a          // OK：参数更宽的函数，可以当窄的用
```

### Covariance and Contravariance

| 位置 | 变型 | 直觉 |
|------|------|------|
| 返回值（输出位） | **协变** covariant | 返回值给得更具体总是安全的 |
| 参数（输入位） | **逆变** contravariant | 必须能吃下所有可能的输入，参数要更宽 |
| 属性（读写） | 不变 invariant（理论）／协变（TS 实现，它是 unsound 的洞） | 属性可写时，协变是不安全的 |

TS 的分界线是 **`strictFunctionTypes`**：选项开启后，**函数类型**的参数位置按逆变检查；但为了兼容历史写法，**方法声明**的参数位置仍然是**双变（bivariant）**，这是一个刻意的 unsound hole。

```typescript
interface Handler {
  handle(x: string): void      // 方法写法：双变
}
interface Fn {
  handle: (x: string) => void  // 属性写法：受 strictFunctionTypes 管
}
```

从 TS 4.7 起可以显式标注变型，用于加速大型递归类型的检查（本质是给检查器一条捷径）：

```typescript
type Getter<out T>   = () => T        // 只产出，协变
type Consumer<in T>  = (t: T) => void // 只消费，逆变
```

常用的泛型设施：

| 设施 | 写法 | 作用 |
|------|------|------|
| 约束 | `<T extends { id: number }>` | 限制上界 |
| 默认值 | `<T = string>` | 省调用时的参数 |
| `keyof` | `keyof T` | 取键的联合类型 |
| 索引类型 | `T[K]` | 按键取值类型 |
| `const` 类型参数 | `<const T extends string[]>` | TS 5.0，推断时不再放宽到宽泛类型 |
| `NoInfer<T>` | `<T>(names: NoInfer<T>[])` | TS 5.4，指定某个位置**不参与**推断 |

## Computation at the Type Level: Type Gymnastics

TS 的类型层是一门纯函数式的迷你语言：有递归、**有条件分支**、有模式匹配（`infer`）、甚至可以尾递归优化到相当深。

### Conditional Types

```typescript
type IsString<T> = T extends string ? true : false

type A = IsString<"abc">   // true
type B = IsString<42>      // false
```

第一个坑：**裸类型参数会触发分配律（distributive conditional type）**。条件类型作用在联合上时，如果 `extends` 左边是裸的类型参数，会对联合的每个成员**分别计算再合并**：

```typescript
type ToArray<T>       = T extends any ? T[] : never
type 分配 = ToArray<string | number>   // string[] | number[]  ← 不是 (string|number)[]

type ToArrayNoDist<T> = [T] extends [any] ? T[] : never
type 不分配 = ToArrayNoDist<string | number>  // (string | number)[]
```

想关掉分配，用 `[T] extends [U]` 包一层把它变成非裸类型。**这条规则几乎是所有类型体操 bug 的源头。**

### infer: Pattern Matching at the Type Level

```typescript
type ReturnType_<T> = T extends (...args: any[]) => infer R ? R : never
type Awaited_<T>    = T extends Promise<infer U> ? U : T

type A = ReturnType_<(x: number) => string>   // string
type B = Awaited_<Promise<number>>            // number
```

递归 + `infer` 就能做字符串拆分：

```typescript
type HeadTail<S extends string> = S extends `${infer H}${infer T}` ? [H, T] : never
type R = HeadTail<"abc">     // ["a", "bc"]
```

顺带一个 TS 7 的真实修复：旧实现按 **UTF-16 code unit** 遍历字符串，遇到 emoji 这种代理对会被切坏，`HeadTail<"😀abc">` 在 TS 6 得到 `["\ud83d", "\ude00abc"]` 半个 emoji。Go 移植版按 Unicode code point 遍历，TS 7 得到 `["😀", "abc"]`。横跨所有非 BMP 字符（emoji、部分 CJK 扩展区）的字符串类型操作因此修正。

### Mapped Types

```typescript
type Optional<T>  = { [K in keyof T]?: T[K] }              // 全部可选
type Readonly_<T> = { readonly [K in keyof T]: T[K] }      // 全部只读
type Required_<T> = { [K in keyof T]-?: T[K] }             // -? 去掉可选
type Mutable<T>   = { -readonly [K in keyof T]: T[K] }     // -readonly 去掉只读
```

`as` 子句支持**键重映射**（TS 4.1），配合模板字面量类型做 getter 工厂：

```typescript
type Getters<T> = {
  [K in keyof T as `get${Capitalize<string & K>}`]: () => T[K]
}

type G = Getters<{ id: number; name: string }>
// { getId: () => number; getName: () => string }
```

内置的字符串操作工具：`Uppercase`、`Lowercase`、`Capitalize`、`Uncapitalize`。

### Where to Stop

类型体操的成本是真实且容易被低估的：

| 症状 | 原因 |
|------|------|
| `Type instantiation is excessively deep and possibly infinite` | 递归深度超限（约 50 层 / 尾部调用优化后约 1000 层） |
| IDE 卡顿、hover 出不来 | 单个类型的实例化成本爆炸，编辑器每次按键都在重算 |
| 报错信息变成几百行 due-diligence 输出 | 错误信息失去定位价值，等于没有报错 |
| 只有作者改得动 | 类型层代码可读性远低于值层的等价实现 |

一个实用的判断准则：**如果一段类型逻辑无法用一句话向同事解释清楚它想表达什么，就该退化成值层代码加显式标注。** 类型系统的价值在于承担文档和重构保障，而不是炫技。真需要复杂推导时，宁可用几条简单的约束手写几份重载，也别写一段谁都不敢碰的递归。

## Soundness Holes (Pitfall Table)

TS 刻意保留了若干 unsound hole。知道它们在哪，比背一百个语法糖有用：

| 坑 | 现象 | 应对 |
|----|------|------|
| `any` 传染 | `const x: number = someAny` 不报错，顺着 `any` 传播一路失去检查 | 用 `unknown`；开 `noImplicitAny`；CI 里禁 `@ts-ignore` |
| 数组协变 | `Dog[]` 可赋给 `Animal[]`，然后往里塞 Cat | 认清 TS 的数组是协变的，Java 也是；写公共 API 用 `readonly T[]` |
| `as` 断言 | `userInput as User` 完全不校验形状 | 断言只是"你比编译器知道得多"的声明，边界数据一律走 schema 校验 |
| 非空断言 `!` | `x!.foo` 关掉 null 检查 | 优先考虑收窄；`!` 应该是一种代码气味 |
| 索引签名的谎言 | `Record<string, string>` 读出来的类型实际是 `string | undefined` | 开 `noUncheckedIndexedAccess` |
| 可选属性的歧义 | `{ x?: number }` 到底是"没有 x"还是"x 是 undefined" | 开 `exactOptionalPropertyTypes` 区分二者 |
| `catch` 变量 | 默认是 `any` | 开 `useUnknownInCatchVariables`（strict 已含） |
| 方法双变 | 方法参数放宽才兼容 | 理解这是刻意为之，别指望 `strictFunctionTypes` 兜住方法写法 |

`any` 与 `unknown` 的区别值得单独强调：

```typescript
function f(x: any)    { x.foo() }   // OK，并且返回值也是 any，一路传染
function g(x: unknown) { x.foo() }  // Error: Object is of type 'unknown'
```

`unknown` 是类型安全的顶层类型——可以接收任何值，但在收窄之前什么都不让做。它是动态数据的正确落点。

### satisfies: Both Inference and Constraints

```typescript
const routes = {
  home: "/",
  user: "/user/:id",
} satisfies Record<string, `/${string}`>

type RouteKey = keyof typeof routes      // "home" | "user"  ← 保留了字面量推断
const r: string = routes.user            // OK
// const bad: string = routes.nope       // Error: 属性不存在
```

用**冒号注解**会把 `routes` 的类型压成 `Record<string, ...>`，丢失具体键；用 `satisfies` 则先按字面量推断，再校验它是否满足约束。这是 TS 4.9 之后写配置对象的标准方式。

## Cooperation with Runtime Boundaries

类型只在编译期存在，边界上进来的数据（HTTP body、JSON 解析、`process.env`、`JSON.parse`）**天然是 `unknown`**。行业惯例是让 schema 成为唯一真相源：

```typescript
import { z } from "zod"

const UserSchema = z.object({ id: z.number(), name: z.string() })
type User = z.infer<typeof UserSchema>     // 类型从 schema 反推

const parsed: User = UserSchema.parse(JSON.parse(body))   // 运行时 + 编译期双重把关
```

这样类型和运行时校验由同一份声明生成，不会漂移。代价是多一层依赖和一点运行时开销，收益是边界安全。

## Links

- [TypeScript](/docs/CS/TypeScript/TypeScript.md)
- [TypeScript 编译器](/docs/CS/TypeScript/Compiler.md)
- [tsconfig 工程配置](/docs/CS/TypeScript/Tsconfig.md)
- [Nodejs](/docs/CS/front-end/Nodejs.md)

## References

- [TypeScript Handbook: Everyday Types](https://www.typescriptlang.org/docs/handbook/2/everyday-types.html)
- [TypeScript Handbook: Narrowing](https://www.typescriptlang.org/docs/handbook/2/narrowing.html)
- [TypeScript Handbook: Conditional Types](https://www.typescriptlang.org/docs/handbook/2/conditional-types.html)
- [TypeScript Handbook: Mapped Types](https://www.typescriptlang.org/docs/handbook/2/mapped-types.html)
- [TypeScript Release Notes](https://www.typescriptlang.org/docs/handbook/release-notes/overview.html)
