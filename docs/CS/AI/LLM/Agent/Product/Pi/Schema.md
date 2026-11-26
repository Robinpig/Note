## Introduction

`pi-schema` 是 v1.5.0 新增、v1.5.2 随 Pi 一并发布的**无 eval JSON Schema 校验器**：schema 只编译一次，变成一堆普通闭包，因此在严格 CSP（禁止 `Function` / `eval`）下也能跑，且零依赖、压缩后 8.5 KiB。覆盖 draft 2020-12 与 7，官方 JSON-Schema-Test-Suite 核心用例通过 2222/2223。本页按 v1.5.2（commit `b4afdddf`）源码核验。

Pi 的工具参数校验从 TypeBox 迁到这个包之后，一条实际影响必须记住：**只有纯 JSON Schema 特性还生效**——TypeBox 的 `Function` / `Symbol`、refinements、codecs，以及 `Intersect` / `Cyclic` / `Ref` 等超出 JSON Schema 的 kind 不再得到校验（ builders 的 `Static` 对其中一部分直接给 `unknown`）。`pi-mcp` 处理外部 server 的 schema 时正是依赖这一点。

三个反直觉点：① `check()` 是**没有分配**的布尔快路径，`errors()` 才在第一次失败时惰性构建解释器；② `compile()` **从不修改** schema，冻结对象也能用；③ 递归 schema 靠一个「间接引用槽」打破缓存环，而不是靠复制 schema。

## Compile to Closures

编译器的设计写在文件头：关键字按它们约束的**类型**分组，值对每个 schema 只分类一次；闭合对象、单 items 数组、tagged union、叶子 schema 这些常见形状各有一个专用闭包。

```ts
// The compiler: a schema to one check closure, built once. Keywords group by the type they constrain, so a value
// is classified once per schema, and the common shapes (closed objects, arrays of one item schema, tagged unions,
// leaf schemas) get one specialized closure each.
export const RESTART = Symbol("restart");

/** One compile of a schema. Its caches and indexes are garbage once the root check is built. */
export class Compiler {
	readonly r: Resolver;
	readonly draft: "2020-12" | "7";
	readonly formats: Readonly<Record<string, FormatCheck>> | undefined;
	/** Whether checks track the dynamic scope (the schema has a bookended `$dynamicRef`). */
	readonly dynamic: boolean;
	private readonly schema: JsonSchema;
	private readonly scope: string[];
	private readonly cache = new Map<object, Check>();
	private readonly annotatingCache = new Map<object, AnnotatingCheck>();
```

`check()` 先做布尔 schema（`true` → `ALWAYS`，`false` → `NEVER`）和 `bareType` 快捷路径；其余先在缓存里放一个 `indirect(slot)` 再递归构建，把递归引用的环打开，构建完再把 slot 指向真闭包：

```ts
	check(node: unknown, base: string): Check {
		if (node === true) return ALWAYS;
		if (node === false) return NEVER;
		if (!isSchemaObject(node))
			throw new Error(`A schema must be an object or a boolean, got ${JSON.stringify(node)}`);
		const cached = this.cache.get(node);
		if (cached !== undefined) return cached;
		const bare = this.bareType(node);
		if (bare !== undefined) return bare;
		const slot: { check: Check | undefined } = { check: undefined };
		this.cache.set(node, indirect(slot));
		const check = this.build(node, this.r.baseFor(node, base));
		slot.check = check;
		this.cache.set(node, check);
		return check;
	}
```

`bareType()` 只认「除注解关键字外只有 `type`」的 schema，把它映射到模块级共享闭包；`plain()` 按 string / number / object / array / bytes 分组，把能合并的关键字合成一个闭包，再用 `typeCheck()` 兜底处理没被分组覆盖的 type。union 还有两级特化：`constUnion()` 把 `{ const: 原始值 }` 分支合成 enum，`tagged()` 识别「每个分支在同一个必填属性上有不同 const」的 tagged union，让一个 tag 值直接选中分支。

对象属性的检查还做了一层**叶子扁平化**：`leaves` 这个 `WeakMap<Check, Leaf>` 把常见检查映射成 `[code, arg]`，code 1–6 是裸类型与 `true`，其余携带参数；`objectCore()` 组装属性表时直接抽出 `leafOf(check)` 的参数与标志位，把「键 / 检查 / 标志」压进一个数组，避免每个属性都走一次闭包调用。这是它在不生成代码的前提下仍接近代码生成速度的关键一环：

```ts
/** The leaf form of `check`, undefined when it is not a leaf. */
export function leafOf(check: Check): Leaf | undefined {
	return leaves.get(check);
}

function leaf(code: number, arg: unknown, check: Check): Check {
	leaves.set(check, [code, arg]);
	return check;
}
```

`$dynamicRef` 是唯一需要**编译两次**的情况：`bookended()` 发现目标带有 `$dynamicAnchor` 时抛 `RESTART`，`compiler()` 捕获后用 `dynamic: true` 重编译，让检查在运行时沿动态作用域查找 anchor。

```ts
function compiler(schema: JsonSchema, options: CompileOptions): Compiler {
	const plain = new Compiler(schema, options, false);
	try {
		plain.root();
		return plain;
	} catch (error) {
		if (error !== RESTART) throw error;
		return new Compiler(schema, options, true);
	}
}
```

## Validator and Lazy Explainer

`compile()` 返回 `Validator<T>`；`check` 是可以直接传递的 type guard，不依赖 validator 实例。`errors()` 先跑快路径，只有失败时才实例化 `Explainer`（它自己重新编译一份 schema，因为解释注解需要不同的检查形态），之后复用：`validate()` 只是把两者合成 `{ ok: true, value }` / `{ ok: false, errors }`，**不改变 value**。

```ts
	/**
	 * Why `value` is invalid: one error per failing keyword, `[]` when it is valid. Built on the first failure and
	 * kept, so a validator whose values always pass never pays for it.
	 */
	errors(value: unknown): ValidationError[] {
		if (this.check(value)) return [];
		this.explainer ??= new Explainer(compiler(this.schema, this.options), this.schema);
		return this.explainer.errors(value);
	}
```

错误用 JSON Pointer 路径报告到具体字段；缺失字段与未知字段分别在字段位置给出 `required` / `additionalProperties`，而不是笼统地说「对象不合法」。源码注释还特意区分 `validate()` 与 TypeBox 的 `Value.Parse`：后者会克隆、填默认值、做转换和删除多余属性，pi-schema 只检查。

## References

`Resolver` 存活于一次编译（或一次解释）期间，索引根 schema 与注册文档的 `$id` / `$anchor` / JSON Pointer。根 schema 没有 `$id` 时用固定基址 `https://json-schema.invalid/root.json`。`unresolvedRefs` 默认是 `"throw"`——编译时遇到悬空 `$ref` 直接失败；改成 `"reject"` 则把该引用编译成 `false`，**只有该位置的值失败、schema 其余部分照常工作**，这是给 MCP server 这类外部来源 schema 准备的：

```ts
	resolve(ref: string, base: string): Resolved {
		this.ensureIndexed();
		if (!this.rejectUnresolved) return this.find(ref, base);
		try {
			return this.find(ref, base);
		} catch {
			this.unresolved.add(resolveUri(ref, base));
			return { node: false, base };
		}
	}
```

## Builders and Static Types

builders 返回**普通 JSON Schema**，`Static<typeof schema>` 从 builder 的参数推导类型；`obj()` 默认闭合（`additionalProperties: false`），`open: true` 才允许额外属性。`recursive<T>(id, self => ...)` 需要显式写类型（TS 无法从 builder 推导递归），`id` 在同一 schema 的递归定义间必须唯一。

`compile()` 接受任意 JSON Schema，不限于 builders 产物。TypeBox 1.x 的 schema 因为是 JSON Schema 可以直接编译，`Static` 会读取 TypeBox 的类型形状给出其静态类型；但 `Intersect` / `Cyclic` / `Ref` 等给 `unknown`，其他 JSON Schema 对象也给 `unknown`。`bytes` / `bigint` / `undefined` 是超出 JSON 的扩展（对应 `Uint8Array` / `bigint` / `undefined`），用于「从不经过 JSON 序列化」的值。

## Pi Integration

Pi 的工具参数校验走 `packages/ai/src/utils/validation.ts`，它把 pi-schema 的三个可选项一次性钉死：格式检查、强制转换、悬空引用局部失败。编译结果按 **schema 对象**放进 `WeakMap` 缓存——工具 schema 是长生命周期对象，工具被回收时条目自动消失，不会泄漏；同一个 schema 反复调用只编译一次：

```ts
// One compiled validator per schema object: tool schemas are long-lived, so the WeakMap drops entries with their tools.
const validatorCache = new WeakMap<object, CoercingValidator>();

function getValidator(schema: Tool["parameters"]): CoercingValidator {
	const cached = validatorCache.get(schema);
	if (cached) {
		return cached;
	}
	// A $ref that names nothing (a dangling definition in an MCP server's schema) rejects only values at its place,
	// instead of making every call of the tool fail.
	const validator = compile(schema, { formats, coerce: true, unresolvedRefs: "reject" });
	validatorCache.set(schema, validator);
	return validator;
}
```

`validateToolArguments()` 先检查 provider 解析阶段留下的 `argumentsError`，再对 `structuredClone(toolCall.arguments)` 做 `parse()`——**复制一份**是为了防止工具修改参数时污染 transcript 里的原始调用。失败时把 JSON Pointer 转成模型可读的点分路径（`/edits/0/oldText` → `edits.0.oldText`），连同收到的参数一起抛错：

```ts
function formatValidationPath(pointer: string): string {
	if (pointer === "") return "root";
	return pointer
		.slice(1)
		.split("/")
		.map((segment) => segment.replace(/~1/g, "/").replace(/~0/g, "~"))
		.join(".");
}
```

这也解释了 v1.5.0 迁移的实际收益：模型常把数字写成 `"42"`、把单值当成数组、把省略的可选属性写成 `null`，`coerce: true` 让这些调用先被规范化再检查，而不是直接判失败。

## Coercion

`coerce: true` 才给 validator 加上 `coerce()` / `parse()`；相关规则在**首次调用**时才构建，所以 `check()` 路径不为它们付任何代价。`coerce()` 只复制发生变化的路径，值没变就原样返回同一个引用，绝不修改输入；`parse()` = `coerce()` + `validate()`。

三趟顺序写死在文件头：

```ts
// Three passes, in this order:
// 1. Optional nulls: a `null` in an optional property whose schema rejects null is dropped, as if omitted.
// 2. Conversion rules ported from TypeBox 1.3.27's Value.Convert (MIT), keyed on JSON Schema structure (`$ref`, `const`,
//    `enum`, `anyOf`/`oneOf`, `allOf`, `type`, `items`/`prefixItems`, `properties`/`patternProperties`) instead of
//    TypeBox's kind marks: `null` becomes "null" for a string, `"3.5"` becomes 3 for an integer, a single value becomes
//    a one-item array, and a union takes the first branch whose conversion passes.
// 3. Primitive coercion by `type` (also type arrays), as in Ajv's `coerceTypes`: what pass 2 left, for example a type
//    array `["integer", "null"]`, or `""` for `null`.
// A value that cannot be coerced is left as it is; the check then reports it.
```

两趟与三趟冲突时**第二趟优先**（必填 string 遇到 `null` 得到 `"null"`，不是 `""`）。递归 schema 的转换有双重防护：`entered` 栈记录正在转换的 `(节点, 值)` 对，重复进入就保持不变，避免无限递归；`memo` 在一次 `coerce()` 调用内缓存 `$ref` 结果，避免递归 union 对每个分支重复转换同一子树。draft 7 的 `additionalItems` **不参与任何一趟**。

## Formats and Cost

`format` 默认是注解、不校验（符合 2020-12）；要真正检查得显式 `import { formats } from "@earendil-works/pi-schema/formats"`，格式集合取自 TypeBox 1.3.27，涵盖 2020-12 定义的全部格式并额外支持 `url` / `json-pointer-uri-fragment`。也可以传自己的 map 只检查部分格式。

README 的基准数据（Node 24.4.1、单核 i9-13900）说明设计取舍：工具 schema 的 `check()` 约 31 ns；编译一个新 schema 约 20 µs、首次 check 0.8 µs；3200 个不同 schema 占 7.1 MB。**严格 CSP 下** Ajv 直接抛 `EvalError`、ata 回退解释器后慢一个数量级，而 pi-schema 保持 164 ns（带 `$ref` 的 MCP 工具 schema）。它不做构建期代码生成，因此既能处理编译期已知的 schema，也能处理运行时到达的 schema（MCP server、扩展、用户输入）。

## Corrections

| 常见误述 | 源码事实 |
| :--- | :--- |
| 「no eval」只是不用 `eval()`，内部仍生成 `new Function` | 编译产物是普通闭包；严格 CSP 下速度不降，Ajv 等代码生成器则直接失败 |
| `errors()` 和 `check()` 开销相同 | `check()` 是无分配的布尔快路径；`errors()` 只在首次失败时惰性构建 Explainer |
| `compile()` 会规范化 / 冻结 schema | 只读不修改，冻结 schema 可直接使用 |
| 迁移到 pi-schema 后 TypeBox 全部能力照旧 | 只有纯 JSON Schema 部分生效；`Function` / `Symbol` / refinements / codecs 与 `Intersect` / `Cyclic` / `Ref` 不再校验。`BigInt` / `Undefined` 是 v1.5.1 补回的例外（本版基线已支持） |
| `format` 默认会校验 | 默认是注解；必须显式导入 `formats` 才检查 |
| 悬空 `$ref` 一律编译失败 | 默认 `"throw"`；`unresolvedRefs: "reject"` 把它变成该位置恒失败的 `false`，供外部 schema 使用 |
| `parse()` 像 TypeBox `Value.Parse` 会克隆并填默认值 | 只做 coerce + check，默认值只是注解，不会被写入 |

## Links

- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [MCP 客户端](/docs/CS/AI/LLM/Agent/Product/Pi/MCP.md)
- [Tools：默认工具集](/docs/CS/AI/LLM/Agent/Product/Pi/Tools.md)
- [CodeMode：脚本调工具](/docs/CS/AI/LLM/Agent/Product/Pi/CodeMode.md)
- [Extensions：扩展体系](/docs/CS/AI/LLM/Agent/Product/Pi/Extensions.md)
- [Telemetry：类型化契约](/docs/CS/AI/LLM/Agent/Product/Pi/Telemetry.md)

## References

- [pi-schema README（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/schema/README.md)
- [编译器：闭包化与动态作用域（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/schema/src/compiler.ts)
- [Validator 与惰性解释（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/schema/src/validator.ts)
- [引用解析（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/schema/src/resolver.ts)
- [强制转换三趟（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/schema/src/coerce.ts)
- [JSON-Schema-Test-Suite](https://github.com/json-schema-org/JSON-Schema-Test-Suite)
