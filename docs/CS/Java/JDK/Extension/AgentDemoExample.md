

## Demo Example

Only will be endless loop at run in IDEA other scenarios will exit normally: 

1. run in Gradle or Maven 
2. run with debug in IDEA 
3. run with java command

Because of the Monitor Ctrl-Break Thread created by IDEA with param -javaagent:/Applications/IntelliJ IDEA.app/Contents/lib/idea_rt.jar={pid}

```java
public class VolatileTest {

    public static volatile int race = 0;

    public static void increase() {
        race++;
    }

    private static final int THREADS_COUNT = 20;

    public static void main(String[] args) {
        Thread[] threads = new Thread[THREADS_COUNT];
        for (int i = 0; i < THREADS_COUNT; i++) {
            new Thread(() -> {
                for (int i1 = 0; i1 < 10000; i1++) {
                    increase();
                }
            }).start();
        }

        //wait for all active Threads terminated
        while (Thread.activeCount() > 1) {
            Thread.yield();
        }
        System.out.println(race);
    }
}
```



MANIFEST.MF file in idea_rt.jar

```
Manifest-Version: 1.0
Ant-Version: Apache Ant 1.10.5
Created-By: 11.0.9.1+11-b1145.77 (JetBrains s.r.o.)
Premain-Class: com.intellij.rt.execution.application.AppMainV2$Agent
```



AppMainV2$Agent

```java
public static void premain(String args, Instrumentation i) {
        AppMainV2.premain(args);
    }
```



AppMainV2

```java
public static void premain(String args) {
    try {
        int p = args.indexOf(58);
        if (p < 0) {
            throw new IllegalArgumentException("incorrect parameter: " + args);
        }

        boolean helperLibLoaded = loadHelper(args.substring(p + 1));
        int portNumber = Integer.parseInt(args.substring(0, p));
        startMonitor(portNumber, helperLibLoaded);
    } catch (Throwable var4) {
        System.err.println("Launcher failed - \"Dump Threads\" and \"Exit\" actions are unavailable (" + var4.getMessage() + ')');
    }

}

private static boolean loadHelper(String binPath) {
    String osName = System.getProperty("os.name").toLowerCase(Locale.ENGLISH);
    if (osName.startsWith("windows")) {
        String arch = System.getProperty("os.arch").toLowerCase(Locale.ENGLISH);
        File libFile = new File(binPath, arch.equals("amd64") ? "breakgen64.dll" : "breakgen.dll");
        if (libFile.isFile()) {
            System.load(libFile.getAbsolutePath());
            return true;
        }
    }

    return false;
}

private static void startMonitor(final int portNumber, final boolean helperLibLoaded) {
    Thread t = new Thread("Monitor Ctrl-Break") {
        public void run() {
            try {
                Socket client = new Socket("127.0.0.1", portNumber);

                try {
                    BufferedReader reader = new BufferedReader(new InputStreamReader(client.getInputStream(), "US-ASCII"));

                    try {
                        while(true) {
                            String msg = reader.readLine();
                            if (msg == null || "TERM".equals(msg)) {
                                return;
                            }

                            if ("BREAK".equals(msg)) {
                                if (helperLibLoaded) {
                                    AppMainV2.triggerControlBreak();
                                }
                            } else if ("STOP".equals(msg)) {
                                System.exit(1);
                            }
                        }
                    } finally {
                        reader.close();
                    }
                } finally {
                    client.close();
                }
            } catch (Exception var14) {
            }
        }
    };
    t.setDaemon(true);
    t.start();
}
```



Reference

- [IDEA Agent](https://mp.weixin.qq.com/s/tZy-SJeMqmLuGLJCmuyXkQ)
- [JVM Threads](https://ifeve.com/jvm-thread/)

