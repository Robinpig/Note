## Introduction

所有 Redis 命令按照以下方式定义：

```
void foobarCommand(client *c) {
    printf("%s",c->argv[1]->ptr); /* Do something with the argument. */
    addReply(c,shared.ok); /* Reply something to the client. */
}
```

命令以某种方式执行后，它会向客户端返回一个回复，通常使用 `addReply()` 或在 `networking.c` 中定义的类似函数。

## 链接
