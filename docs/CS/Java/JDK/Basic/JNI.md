## Introduction


Java Native Interface



## native call Java

```c
#include<jni.h>
```



Pointer of JVM 

Pointer of JNIEnv : *env

JNI_createJavaVM



JNI_DestroyJavaVM





for example

java -jar spring-application.jar  using Java Launcher   - -   JNI - - > libjvm.so



## Java call native



## Thread



state in native is RUNNABLE



## JNI and safepoint



## JNI and GC



## References

1. [Java Programming Tutorial Java Native Interface (JNI)](https://www3.ntu.edu.sg/home/ehchua/programming/java/JavaNativeInterface.html)
2. [Java Native Interface Specification Contents](https://docs.oracle.com/en/java/javase/11/docs/specs/jni/index.html)
