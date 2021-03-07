# Tools



- jcmd 它用来打印Java进程所涉及的基本类、线程和VM信息
- jconsole提供JVM活动的图形化视图，包括线程的使用、类的使用和GC活动。
-  jhat读取内存堆转储，并有助于分析。这是事后使用的工具。•
- jmap提供堆转储和其他JVM内存使用的信息。可以适用于脚本，但堆转储必须在事后分析工具中使用。•
- jinfo查看JVM的系统属性，可以动态设置一些系统属性。可适用于脚本。
-  jstack转储Java进程的栈信息。可适用于脚本。
-  jstat提供GC和类装载活动的信息。可适用于脚本
-  jvisualvm监视JVM的GUI工具，可用来剖析运行的应用，分析JVM堆转储（事后活动，虽然jvisualvm也可以实时抓取程序的堆转储



## jps

jps -l	显示Java进程



## jcmd

jcmd process_id command optional_arguments

| Command   | --   |
| --------- | ---- |
| VM.uptime |      |



## jinfo

jinfo command process_id

|        |                                  |
| ------ | -------------------------------- |
| -flags | Get flages of process            |
| -flag  | check or update manageable flags |



## jstack

jstack process_id  == jcmd process_id Thread.print



## JMC



## JFR

