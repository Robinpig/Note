## Introduction

[Gson](https://github.com/google/gson) 是一个 Java 库，可用于将 Java 对象转换为其 JSON 表示形式。
它也可以用于将 JSON 字符串转换为等效的 Java 对象。
Gson 可以处理任意 Java 对象，包括那些你没有源代码的现有对象。

> [!Note]
> 
> Gson is currently in maintenance mode; existing bugs will be fixed, but large new features will likely not be added.

GSON 通过 GsonBuilder 提供两种方式来排除 JSON 中的字段：

- `@Expose Annotation`</br>
  使用 @Expose 注解，然后在 GsonBuilder 上调用 excludeFieldsWithoutExposeAnnotation() 方法，将忽略除使用 @Expose 注解暴露的字段之外的所有字段。
- `Custom Annotation`</br>
  通过定义自定义注解，并扩展 ExclusionStrategy 接口忽略带有排除类注解的字段，使用以下 GsonBuilder 方法可以实现从 JSON 中忽略/排除字段。

## Links

- [Jackson](/docs/CS/Java/Jackson.md)
