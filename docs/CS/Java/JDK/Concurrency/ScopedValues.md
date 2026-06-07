## Introduction

Scoped values 支持在线程内部和跨线程之间安全高效地共享不可变数据。
它们优于 thread-local 变量，尤其是在使用大量 [virtual threads](/docs/CS/Java/JDK/Concurrency/VirtualThread.md) 时。
