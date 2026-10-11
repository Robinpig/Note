## Introduction

本页是 [Java Agent](/docs/CS/Java/JDK/Agent.md)、[Instrumentation](/docs/CS/Java/JDK/Basic/Instrumentation.md) 与 [ASM](/docs/CS/Java/JDK/ASM.md) 的实战延伸：用一个"方法计时 agent"把三篇的理论串成可运行的代码。它能在**不修改业务源码**的前提下，于类加载期（load-time instrumentation）给指定方法插入计时逻辑。完整链路是：`premain` 入口 → `Instrumentation.addTransformer` → `ClassFileTransformer.transform` 拿到原始字节码 → ASM 改写 → 返回新字节码由 JVM 定义。

## A Minimal Agent

Agent 的入口是 `premain`（静态加载，经 `-javaagent` 指定）。它唯一要做的是把一个 `ClassFileTransformer` 注册进 `Instrumentation`：

```java
// TimingAgent.java
package com.example.agent;

import java.lang.instrument.Instrumentation;

public class TimingAgent {
    public static void premain(String args, Instrumentation inst) {
        inst.addTransformer(new TimingTransformer());
    }
}
```

要让 `-javaagent` 能找到它，jar 的 manifest 必须声明 `Premain-Class`（以及声明允许 redefine/retransform，方便 attach 场景）：

```
Premain-Class: com.example.agent.TimingAgent
Can-Redefine-Classes: true
Can-Retransform-Classes: true
```

## Bytecode Instrumentation

`ClassFileTransformer.transform` 在**每个类被定义前**被调用，拿到的是该类原始的 `byte[]`。我们选择目标类（`className` 是 JVM 内部名，点号替换为斜杠），用 ASM 的 `ClassReader` 解析、`ClassWriter` 重写，只对 `doWork` 方法插入进入/退出日志：

```java
// TimingTransformer.java
package com.example.agent;

import java.lang.instrument.ClassFileTransformer;
import java.security.ProtectionDomain;
import org.objectweb.asm.*;

public class TimingTransformer implements ClassFileTransformer {
    private static final String TARGET = "com/example/BusinessService";

    @Override
    public byte[] transform(ClassLoader loader, String className,
                            Class<?> classBeingRedefined,
                            ProtectionDomain domain, byte[] buf) {
        if (!TARGET.equals(className)) return null;   // 非目标类返回 null，原样加载
        ClassReader cr = new ClassReader(buf);
        ClassWriter cw = new ClassWriter(cr, ClassWriter.COMPUTE_MAXS);
        cr.accept(new ClassVisitor(Opcodes.ASM9, cw) {
            @Override
            public MethodVisitor visitMethod(int acc, String name,
                                             String desc, String sig, String[] ex) {
                MethodVisitor mv = super.visitMethod(acc, name, desc, sig, ex);
                if ("doWork".equals(name)) {
                    return new TimingMethodAdapter(mv, name);
                }
                return mv;
            }
        }, 0);
        return cw.toByteArray();
    }
}
```

`COMPUTE_MAXS` 让 ASM 帮我们重算操作数栈与局部变量表大小（注意：若需 `COMPUTE_FRAMES` 且涉及跨类继承链，必须重写 `getCommonSuperClass` 否则会触发类加载死锁，详见 [ASM](/docs/CS/Java/JDK/ASM.md)）。

`TimingMethodAdapter` 在方法体开头插入日志，演示字节码插入的位置；把日志换成 `System.nanoTime()` 的前后取值，即得到真正的方法计时：

```java
// TimingMethodAdapter.java
package com.example.agent;

import org.objectweb.asm.*;

public class TimingMethodAdapter extends MethodVisitor {
    private final String methodName;
    public TimingMethodAdapter(MethodVisitor mv, String name) {
        super(Opcodes.ASM9, mv);
        this.methodName = name;
    }
    @Override
    public void visitCode() {
        mv.visitFieldInsn(GETSTATIC, "java/lang/System", "err", "Ljava/io/PrintStream;");
        mv.visitLdcInsn("[agent] enter " + methodName);
        mv.visitMethodInsn(INVOKEVIRTUAL, "java/io/PrintStream",
                           "println", "(Ljava/lang/String;)V", false);
        super.visitCode();
    }
}
```

## Build and Run

maven 用 `maven-jar-plugin` 把 manifest 写进 jar（依赖 `org.ow2.asm:asm`）：

```xml
<plugin>
  <groupId>org.apache.maven.plugins</groupId>
  <artifactId>maven-jar-plugin</artifactId>
  <configuration>
    <archive>
      <manifestEntries>
        <Premain-Class>com.example.agent.TimingAgent</Premain-Class>
        <Can-Redefine-Classes>true</Can-Redefine-Classes>
        <Can-Retransform-Classes>true</Can-Retransform-Classes>
      </manifestEntries>
    </archive>
  </configuration>
</plugin>
```

打包后在启动业务程序时挂上 agent 即可，无需改一行业务代码：

```bash
java -javaagent:timing-agent.jar -jar app.jar
```

> [!TIP]
> 若 agent 与业务程序不在同一 classpath，或要对**已运行**的 JVM 注入，应改用 `agentmain` 入口（见 [Lifecycle](/docs/CS/Java/JDK/Agent.md?id=lifecycle)）+ Attach API，经 `VirtualMachine.loadAgent` 触发 `retransformClasses`。

## Real World Case: IDEA Agent

IntelliJ IDEA 自身就是一个 agent 的使用者。它在启动你的程序时，通过 `-javaagent:/Applications/IntelliJ IDEA.app/Contents/lib/idea_rt.jar={pid}` 注入自己的 agent：

```java
// idea_rt.jar 中的入口（节选）
public static void premain(String args, Instrumentation i) {
    AppMainV2.premain(args);
}
```

`AppMainV2.premain` 解析出端口号后启动一个名为 **"Monitor Ctrl-Break"** 的守护线程，监听本地端口，从而让 IDE 的 "Dump Threads" / "Exit" 按钮能向 JVM 发指令：

```java
private static void startMonitor(final int portNumber, final boolean helperLibLoaded) {
    Thread t = new Thread("Monitor Ctrl-Break") {
        public void run() {
            try (Socket client = new Socket("127.0.0.1", portNumber);
                 BufferedReader reader = new BufferedReader(
                     new InputStreamReader(client.getInputStream(), "US-ASCII"))) {
                while (true) {
                    String msg = reader.readLine();
                    if (msg == null || "TERM".equals(msg)) return;
                    if ("BREAK".equals(msg)) { /* 触发线程 dump */ }
                    else if ("STOP".equals(msg)) System.exit(1);
                }
            } catch (Exception ignored) {}
        }
    };
    t.setDaemon(true);
    t.start();
}
```

这也解释了为什么某些程序（例如下面这个 `VolatileTest`）在 IDEA 里以 **debug / 普通 run** 启动时不会像命令行那样自然退出——agent 注入的线程维持了 JVM 存活；只有在 Gradle/Maven 或裸 `java` 命令下才按预期退出：

```java
public class VolatileTest {
    public static volatile int race = 0;
    public static void increase() { race++; }

    public static void main(String[] args) {
        Thread[] threads = new Thread[20];
        for (int i = 0; i < 20; i++) {
            threads[i] = new Thread(() -> {
                for (int k = 0; k < 10000; k++) increase();
            });
            threads[i].start();
        }
        while (Thread.activeCount() > 1) Thread.yield();
        System.out.println(race);
    }
}
```

## Links

- [Agent](/docs/CS/Java/JDK/Agent.md)
- [Instrumentation](/docs/CS/Java/JDK/Basic/Instrumentation.md)
- [ASM](/docs/CS/Java/JDK/ASM.md)
- [JDK](/docs/CS/Java/JDK/JDK.md)

## References

1. [IDEA Agent](https://mp.weixin.qq.com/s/tZy-SJeMqmLuGLJCmuyXkQ)
2. [JVM Threads](https://ifeve.com/jvm-thread/)
