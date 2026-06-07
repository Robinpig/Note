## Introduction

Phaser 提供了一种更灵活的 barrier 形式，可用于控制多线程之间的分阶段计算。
一种可重用的同步屏障，功能类似于 CyclicBarrier 和 CountDownLatch，但支持更灵活的使用。

```java
public Phaser() {
    this(null, 0);
}

public Phaser(Phaser parent, int parties) {
  if (parties >>> PARTIES_SHIFT != 0)
    throw new IllegalArgumentException("Illegal number of parties");
  int phase = 0;
  this.parent = parent;
  if (parent != null) {
    final Phaser root = parent.root;
    this.root = root;
    this.evenQ = root.evenQ;
    this.oddQ = root.oddQ;
    if (parties != 0)
      phase = parent.doRegister(1);
  }
  else {
    this.root = this;
    this.evenQ = new AtomicReference<QNode>();
    this.oddQ = new AtomicReference<QNode>();
  }
  this.state = (parties == 0) ? (long)EMPTY :
    ((long)phase << PHASE_SHIFT) | ((long)parties << PARTIES_SHIFT) | ((long)parties);
}
```

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
