## Introduction


```cpp
#include <thread>

void main(int argc, char const *argv[])
{
    std::thread t(hello);
}
```

## Mechanism

### mutex

```cpp
std::mutex

std::lock_guard<>
std::unique_lock<>
```

### Future
future promise

### latch
latch

barrier

### Atomic
atomic

## Memory Model

Three models with six memory ordering options:
- relaxed ordering 
  - memory_order_relaxed
- acquire-release ordering 
  - memory_order_consume
  - memory_order_acquire
  - memory_order_release
  - memory_order_acq_rel
- sequentially consistent ordering 
  - memory_order_seq_cst
    
多线程下未同步的并发写构成**数据竞争**，属于 [未定义行为](/docs/CS/C++/UB.md)。

## Links

- [C++](/docs/CS/C++/C++.md)
- [未定义行为](/docs/CS/C++/UB.md)
- [Java Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
