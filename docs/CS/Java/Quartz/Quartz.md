## Introduction

[Quartz](http://www.quartz-scheduler.org/) is a richly featured, open source job scheduling library that can be integrated within virtually any Java application - from the smallest stand-alone application to the largest e-commerce system.

- Scheduler、 
- Trigger: SimpleTrigger, CronTrigger, 
- Job、JobDetail
- JobDataMap
- JobExecutionContext



- Scheduler为调度器负责整个定时系统的调度，内部通过线程池进行调度，下文阐述。

- Trigger为触发器记录着调度任务的时间规则，主要有四种类型：SimpleTrigger、CronTrigger、DataIntervalTrigger、NthIncludedTrigger，在项目中常用的为：SimpleTrigger和CronTrigger。

- JobDetail为定时任务的信息载体，可以记录Job的名字、组及任务执行的具体类和任务执行所需要的参数

- Job为任务的真正执行体，承载着具体的业务逻辑。

元素之间的关系如下：

介绍：先由SchedulerFactory创建Scheduler调度器后，由调度器去调取即将执行的Trigger，执行时获取到对于的JobDetail信息，找到对应的Job类执行业务逻辑。

quartz中线程主要分为执行线程和调度线程。

- 执行线程主要由一个线程池维护，在需要执行定时的时候使用

- 调度线程主要分为regular Scheduler Thread和Misfire Scheduler Thread；其中Regular Thread 轮询Trigger，如果有将要触发的Trigger，则从任务线程池中获取一个空闲线程，然后执行与改Trigger关联的job；Misfire Thraed则是扫描所有的trigger，查看是否有错失的，如果有的话，根据一定的策略进行处理。

## start



当服务器启动时，Spring就加载相关的bean。SchedulerFactoryBean实现了InitializingBean接口，因此在初始化bean的时候，会执行afterPropertiesSet方法，该方法将会调用SchedulerFactory(DirectSchedulerFactory 或者 StdSchedulerFactory，通常用StdSchedulerFactory)创建Scheduler。我们在SchedulerFactoryBean配置类中配了相关的配置及配置文件参数，所以会读取配置文件参数，初始化各个组件。关键组件如下：

- ThreadPool:既上面所说的执行线程，一般是使用SimpleThreadPool(线程数量固定的线程池),SimpleThreadPool创建了一定数量的WorkerThread实例来使得Job能够在线程中进行处理。WorkerThread是定义在SimpleThreadPool类中的内部类，它实质上就是一个线程。在SimpleThreadPool中有三个list：workers-存放池中所有的线程引用，availWorkers-存放所有空闲的线程，busyWorkers-存放所有工作中的线程；配置如下

org.quartz.threadPool.class=org.quartz.simpl.SimpleThreadPool
org.quartz.threadPool.threadCount=3
org.quartz.threadPool.threadPriority=5
- JobStore初始化定时任务的数据存储方式，分为两种：存储在内存的RAMJobStore和存储在数据库的JobStoreSupport(包括JobStoreTX和JobStoreCMT两种实现，JobStoreCMT是依赖于容器来进行事务的管理，而JobStoreTX是自己管理事务），若要使用集群要使用JobStoreSupport的方式；

- QuartzSchedulerThread初始化调度线程，在初始化的时候paused=true,halted=false,虽然线程开始运行了，但是paused=true，线程会一直等待，直到start方法将paused置为false；SchedulerFactoryBean还实现了SmartLifeCycle接口，因此初始化完成后，会执行start()方法，该方法将主要会执行以下的几个动作：

1. 创建ClusterManager线程并启动线程:该线程用来进行集群故障检测和处理

2. 创建MisfireHandler线程并启动线程:该线程用来进行misfire任务的处理

3. 置QuartzSchedulerThread的paused=false，调度线程才真正开始调度

整个启动流程图如下：


流程图简要说明：

1. 先读取配置文件

2. 初始化SchedulerFactoryBean

3. 初始化SchedulerFactory

4. 实例化执行线程池（TheadPool）

5. 实例化数据存储

6. 初始化QuartzScheduler(为Scheduler的简单实现，包括调度作业、注册JobListener实例等方法。)

7. new一个QuartzSchedulerThread调度线程（负责执行在QuartzScheduler中注册的触发触发器的线程。），并开始运行

8. 调度开始，注册监听器，注册Job和Trigger

9. SchedulerFactoryBean初始化完成后执行start()方法

10. 创建ClusterManager线程并启动线程

11. 创建MisfireHandler线程并启动线程

12. 置QuartzSchedulerThread的paused=false，调度线程真正开始调度，开始执行run方法

QuartzSchedulerThread逻辑具体介绍：
类中主要的方法就是run方法，下面主要对run方法进行介绍：

//只有当Quartzscheduler执行start方法时被调用
void togglePause(boolean pause) {
synchronized(this.sigLock) {
this.paused = pause;
if (this.paused) {
this.signalSchedulingChange(0L);
} else {
this.sigLock.notifyAll();
}

        }
    }
public void run() {
boolean lastAcquireFailed = false;

        label214:
        //此处判断调度器是否终止
         while(!this.halted.get()) {
                    try {
                        synchronized(this.sigLock) {
                            //此处判断调度器是否终止或是否暂停，由于我们在初始化的时候
                            //将paused=true，那么调度线程此时不会真正开始执行只会在不断循环阻塞
                            //只有当Quartzscheduler执行start方法时调用togglePause开始将
                            //paused置为false,run方法开始真正运行
                            while(this.paused && !this.halted.get()) {
                                try {
                                    this.sigLock.wait(1000L);
                                } catch (InterruptedException var23) {
                                }
                            }
        
                            if (this.halted.get()) {
                                break;
                            }
                        }
                        //取出执行线程池中空闲的线程数量
                        int availThreadCount = this.qsRsrcs.getThreadPool().blockForAvailableThreads();
                        if (availThreadCount > 0) {
                        ...
                        ...
                        //如果可用线程数量足够那么查看30秒内需要触发的触发器。如果没有的
                        //话那么就是30后再次扫描，其中方法中三个参数idleWaitTime为如果
                        //没有的再次扫描的时间，第二个为最多取几个，最后一个参数
                        //batchTimeWindow，这个参数默认是0，同样是一个时间范围，如果
                        //有两个任务只差一两秒，而执行线程数量满足及batchTimeWindow时间
                        //也满足的情况下就会两个都取出来
                        
                        triggers = this.qsRsrcs.getJobStore().acquireNextTriggers(now + this.idleWaitTime, Math.min(availThreadCount, this.qsRsrcs.getMaxBatchSize()), this.qsRsrcs.getBatchTimeWindow());
                        ...
                        ...
                        //trigger列表是以下次执行时间排序查出来的
                        //在列表不为空的时候进行后续操作
                        if (triggers != null && !triggers.isEmpty()) {
                        now = System.currentTimeMillis();
                        //取出集合中最早执行的触发器
                        long triggerTime = ((OperableTrigger)triggers.get(0)).getNextFireTime().getTime();
                        //判断距离执行时间是否大于两毫秒
                        for(long timeUntilTrigger = triggerTime - now; timeUntilTrigger > 2L; timeUntilTrigger = triggerTime - now) {
                            synchronized(this.sigLock) {
                                if (this.halted.get()) {
                                    break;
                                }
                                //判断是否还有更早的trigger
                                if (!this.isCandidateNewTimeEarlierWithinReason(triggerTime, false)) {
                                //没有的话进行简单的阻塞，到时候再执行
                                    try {
                                        now = System.currentTimeMillis();
                                        timeUntilTrigger = triggerTime - now;
                                        if (timeUntilTrigger >= 1L) {
                                            this.sigLock.wait(timeUntilTrigger);
                                        }
                                    } catch (InterruptedException var22) {
                                    }
                                }
                            }
                            //开始根据需要执行的trigger从数据库中获取相应的JobDetail
                               if (goAhead) {
                                try {
                                    List<TriggerFiredResult> res = this.qsRsrcs.getJobStore().triggersFired(triggers);
                                    if (res != null) {
                                        bndles = res;
                                    }
                                } catch (SchedulerException var24) {
                                    this.qs.notifySchedulerListenersError("An error occurred while firing triggers '" + triggers + "'", var24);
                                    int i = 0;
    
                                    while(true) {
                                        if (i >= triggers.size()) {
                                            continue label214;
                                        }
    
                                        this.qsRsrcs.getJobStore().releaseAcquiredTrigger((OperableTrigger)triggers.get(i));
                                        ++i;
                                    }
                                }
                            }
                            //将查询到的结果封装成为 TriggerFiredResult
                             for(int i = 0; i < ((List)bndles).size(); ++i) {
                                TriggerFiredResult result = (TriggerFiredResult)((List)bndles).get(i);
                                TriggerFiredBundle bndle = result.getTriggerFiredBundle();
                                Exception exception = result.getException();
                                if (exception instanceof RuntimeException) {
                                    this.getLog().error("RuntimeException while firing trigger " + triggers.get(i), exception);
                                    this.qsRsrcs.getJobStore().releaseAcquiredTrigger((OperableTrigger)triggers.get(i));
                                } else if (bndle == null) {
                                    this.qsRsrcs.getJobStore().releaseAcquiredTrigger((OperableTrigger)triggers.get(i));
                                } else {
                                    JobRunShell shell = null;
    
                                    try {
                                    //把任务封装成JobRunShell线程任务，然后放到线程池中跑动。
                                        shell = this.qsRsrcs.getJobRunShellFactory().createJobRunShell(bndle);
                                        shell.initialize(this.qs);
                                    } catch (SchedulerException var27) {
                                        this.qsRsrcs.getJobStore().triggeredJobComplete((OperableTrigger)triggers.get(i), bndle.getJobDetail(), CompletedExecutionInstruction.SET_ALL_JOB_TRIGGERS_ERROR);
                                        continue;
                                    }
                                    //runInThread方法加Job放入对应的工作线程进行执行Job
                                    if (!this.qsRsrcs.getThreadPool().runInThread(shell)) {
                                        this.getLog().error("ThreadPool.runInThread() return false!");
                                        this.qsRsrcs.getJobStore().triggeredJobComplete((OperableTrigger)triggers.get(i), bndle.getJobDetail(), CompletedExecutionInstruction.SET_ALL_JOB_TRIGGERS_ERROR);
                                    }
                                }
                            }


整个QuartzSchedulerThread的重要的run方法的介绍就如上，总结下来：

1. 先获取线程池中的可用线程数量（若没有可用的会阻塞，直到有可用的）；

2. 获取30m内要执行的trigger(即acquireNextTriggers)获取trigger的锁，通过select …for update方式实现；获取30m内（可配置）要执行的triggers（需要保证集群节点的时间一致），若@ConcurrentExectionDisallowed且列表存在该条trigger则跳过，否则更新trigger状态为ACQUIRED(刚开始为WAITING)；插入firedTrigger表，状态为ACQUIRED;（注意：在RAMJobStore中，有个timeTriggers，排序方式是按触发时间nextFireTime排的；JobStoreSupport从数据库取出triggers时是按照nextFireTime排序）;

3. 待直到获取的trigger中最先执行的trigger在2ms内；

4. triggersFired：

①更新firedTrigger的status=EXECUTING;

②更新trigger下一次触发的时间；

③更新trigger的状态：无状态的trigger->WAITING，有状态的trigger->BLOCKED，若nextFireTime==null ->COMPLETE；

④ commit connection,释放锁；

5. 针对每个要执行的trigger，创建JobRunShell，并放入线程池执行：

- execute:执行job

- 获取TRIGGER_ACCESS锁

- 若是有状态的job：更新trigger状态：BLOCKED->WAITING,PAUSED_BLOCKED->BLOCKED

- 若@PersistJobDataAfterExecution，则updateJobData

- 删除firedTrigger

- commit connection，释放锁

流程图如下：


misfireHandler线程

下面这些原因可能造成 misfired job:

1. 系统因为某些原因被重启。在系统关闭到重新启动之间的一段时间里，可能有些任务会被 misfire；

2. Trigger 被暂停（suspend）的一段时间里，有些任务可能会被 misfire；

3. 线程池中所有线程都被占用，导致任务无法被触发执行，造成 misfire；

4. 有状态任务在下次触发时间到达时，上次执行还没有结束；为了处理 misfired job，Quartz 中为 trigger定义了处理策略，主要有下面两种：MISFIRE_INSTRUCTION_FIRE_ONCE_NOW：针对 misfired job马上执行一次；MISFIRE_INSTRUCTION_DO_NOTHING：忽略 misfired job，等待下次触发；默认是MISFIRE_INSTRUCTION_SMART_POLICY，该策略在CronTrigger中=MISFIRE_INSTRUCTION_FIRE_ONCE_NOW线程默认1分钟执行一次；在一个事务中，默认一次最多recovery 20个；

执行流程：

1. 若配置(默认为true，可配置)成获取锁前先检查是否有需要recovery的trigger，先获取misfireCount；

2. 获取TRIGGER_ACCESS锁；

3. hasMisfiredTriggersInState：获取misfired的trigger，默认一个事务里只能最大20个misfired trigger（可配置），misfired判断依据：status=waiting,next_fire_time < current_time-misfirethreshold(可配置，默认1min)

4. notifyTriggerListenersMisfired

5. updateAfterMisfire:获取misfire策略(默认是MISFIRE_INSTRUCTION_SMART_POLICY，该策略在CronTrigger中=MISFIRE_INSTRUCTION_FIRE_ONCE_NOW)，根据策略更新nextFireTime；

6. 将nextFireTime等更新到trigger表；

7. commit connection，释放锁8.如果还有更多的misfired，sleep短暂时间(为了集群负载均衡)，否则sleep misfirethreshold时间，后继续轮询；

misfireHandler线程执行流程如下图所示：


另附一个个人问题：
因为QuartzSchedulerThread的run方法默认会每30秒去取30秒内需要执行的trigger，测试发现如果我扫描时间是在17:49:50秒，我在扫描后创建一个17:49:52就要执行的任务，那么这个任务就会到了52时不执行，而是延迟几秒执行，自己猜测原因：因为扫描时间已经过了在下一次扫描时只会扫描30秒内需要执行的任务，但是我后创的那个任务在下一次扫描之前已经执行了，而延迟几秒后就执行的原因猜测是因为那个任务变为misfire任务，被misfireHandler线程扫描到按照配置的策略执行了，因此并会出现到了时间没有执行但是过了几秒后自己执行了的现象。

