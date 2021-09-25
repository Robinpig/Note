## Introduction

JDK

- TimeTask
  Timer does have support for scheduling based on absolute, not relative time, so that tasks can be sensitive to changes in the system clock;
- ScheduledExecuteService
  ScheduledThreadPoolExecutor supports only relative time.

线程角度
Timer是单线程模式，如果某个TimerTask任务的执行时间比较久，会影响到其他任务的调度执
行。
ScheduledThreadPoolExecutor是多线程模式，并且重用线程池，某个ScheduledFutureTask任
务执行的时间比较久，不会影响到其他任务的调度执行。
系统时间敏感度
Timer调度是基于操作系统的绝对时间的，对操作系统的时间敏感，一旦操作系统的时间改变，则
Timer的调度不再精确。
ScheduledThreadPoolExecutor调度是基于相对时间的，不受操作系统时间改变的影响。
是否捕获异常
Timer不会捕获TimerTask抛出的异常，加上Timer又是单线程的。一旦某个调度任务出现异常，
则整个线程就会终止，其他需要调度的任务也不再执行。
ScheduledThreadPoolExecutor基于线程池来实现调度功能，某个任务抛出异常后，其他任务仍
能正常执行

任务是否具备优先级
Timer中执行的TimerTask任务整体上没有优先级的概念，只是按照系统的绝对时间来执行任务。
ScheduledThreadPoolExecutor中执行的ScheduledFutureTask类实现了java.lang.Comparable
接口和java.util.concurrent.Delayed接口，这也就说明了ScheduledFutureTask类中实现了两个非
常重要的方法，一个是java.lang.Comparable接口的compareTo方法，一个是
java.util.concurrent.Delayed接口的getDelay方法。在ScheduledFutureTask类中compareTo方
法方法实现了任务的比较，距离下次执行的时间间隔短的任务会排在前面，也就是说，距离下次执
行的时间间隔短的任务的优先级比较高。而getDelay方法则能够返回距离下次任务执行的时间间
隔。
是否支持对任务排序
Timer不支持对任务的排序。
ScheduledThreadPoolExecutor类中定义了一个静态内部类DelayedWorkQueue，
DelayedWorkQueue类本质上是一个有序队列，为需要调度的每个任务按照距离下次执行时间间
隔的大小来排序
能否获取返回的结果
Timer中执行的TimerTask类只是实现了java.lang.Runnable接口，无法从TimerTask中获取返回的
结果。
ScheduledThreadPoolExecutor中执行的ScheduledFutureTask类继承了FutureTask类，能够通
过Future来获取返回的结果

它们仅支持按照指定频率，不**直接**支持指定时间的定时调度，需要我们结合 Calendar 自行计算，才能实现复杂时间的调度。例如说，每天、每周五、2019-11-11 等等。

它们是进程级别，而我们为了实现定时任务的高可用，需要部署多个进程。此时需要等多考虑，多个进程下，同一个任务在相同时刻，不能重复执行。

项目可能存在定时任务较多，需要统一的管理，此时不得不进行二次封装。



Spring Task

Quartz



Elastic-Job

XXL-JOB