## Introduction

[Quartz](http://www.quartz-scheduler.org/) is a richly featured, open source job scheduling library that can be integrated within virtually any Java application - from the smallest stand-alone application to the largest e-commerce system. Quartz can be used to create simple or complex schedules for executing tens, hundreds, or even tens-of-thousands of jobs; jobs whose tasks are defined as standard Java components that may execute virtually anything you may program them to do. The Quartz Scheduler includes many enterprise-class features, such as support for JTA transactions and clustering.

### JobDetail
Conveys the detail properties of a given Job instance. JobDetails are to be created/defined with JobBuilder.
Quartz does not store an actual instance of a Job class, but instead allows you to define an instance of one, through the use of a JobDetail.
Jobs have a name and group associated with them, which should uniquely identify them within a single Scheduler.
Triggers are the 'mechanism' by which Jobs are scheduled. Many Triggers can point to the same Job, but a single Trigger can only point to one Job.


### Trigger
The base interface with properties common to all Triggers - use TriggerBuilder to instantiate an actual Trigger.
Triggerss have a TriggerKey associated with them, which should uniquely identify them within a single Scheduler.
Triggers are the 'mechanism' by which Jobs are scheduled. Many Triggers can point to the same Job, but a single Trigger can only point to one Job.
Triggers can 'send' parameters/data to Jobs by placing contents into the JobDataMap on the Trigger.

### JobExecutionContext
A context bundle containing handles to various environment information, that is given to a JobDetail instance as it is executed, and to a Trigger instance after the execution completes.
The JobDataMap found on this object (via the getMergedJobDataMap() method) serves as a convenience - it is a merge of the JobDataMap found on the JobDetail and the one found on the Trigger, with the value in the latter overriding any same-named values in the former. It is thus considered a 'best practice' that the execute code of a Job retrieve data from the JobDataMap found on this object NOTE: Do not expect value 'set' into this JobDataMap to somehow be set back onto a job's own JobDataMap - even if it has the @PersistJobDataAfterExecution annotation.
JobExecutionContext s are also returned from the Scheduler.getCurrentlyExecutingJobs() method. These are the same instances as those passed into the jobs that are currently executing within the scheduler. The exception to this is when your application is using Quartz remotely (i.e. via RMI) - in which case you get a clone of the JobExecutionContexts, and their references to the Scheduler and Job instances have been lost (a clone of the JobDetail is still available - just not a handle to the job instance that is running).
#### getMergedJobDataMap
Get the convenience JobDataMap of this execution context.
The JobDataMap found on this object serves as a convenience - it is a merge of the JobDataMap found on the JobDetail and the one found on the Trigger, with the value in the latter overriding any same-named values in the former. It is thus considered a 'best practice' that the execute code of a Job retrieve data from the JobDataMap found on this object.
NOTE: Do not expect value 'set' into this JobDataMap to somehow be set or persisted back onto a job's own JobDataMap - even if it has the @PersistJobDataAfterExecution annotation.
Attempts to change the contents of this map typically result in an IllegalStateException.
```java
// 
public JobDataMap getMergedJobDataMap();
```

### JobbDataMap
Holds state information for Job instances.
JobDataMap instances are stored once when the Job is added to a scheduler. They are also re-persisted after every execution of jobs annotated with @PersistJobDataAfterExecution.
JobDataMap instances can also be stored with a Trigger. This can be useful in the case where you have a Job that is stored in the scheduler for regular/repeated use by multiple Triggers, yet with each independent triggering, you want to supply the Job with different data inputs.
The JobExecutionContext passed to a Job at execution time also contains a convenience JobDataMap that is the result of merging the contents of the trigger's JobDataMap (if any) over the Job's JobDataMap (if any).
Update since 2.2.4 - We keep an dirty flag for this map so that whenever you modify(add/delete) any of the entries, it will set to "true". However if you create new instance using an exising map with JobDataMap(Map), then the dirty flag will NOT be set to "true" until you modify the instance.


### Scheduler
This is the main interface of a Quartz Scheduler.
A Scheduler maintains a registry of JobDetails and Triggers. **Once registered, the Scheduler is responsible for executing Job s when their associated Trigger s fire (when their scheduled time arrives).**
Scheduler instances are produced by a SchedulerFactory. A scheduler that has already been created/initialized can be found and used through the same factory that produced it. After a Scheduler has been created, it is in "stand-by" mode, and must have its start() method called before it will fire any Jobs.
Job s are to be created by the 'client program', by defining a class that implements the Job interface. JobDetail objects are then created (also by the client) to define a individual instances of the Job. JobDetail instances can then be registered with the Scheduler via the scheduleJob(JobDetail, Trigger) or addJob(JobDetail, boolean) method.
Trigger s can then be defined to fire individual Job instances based on given schedules. SimpleTrigger s are most useful for one-time firings, or firing at an exact moment in time, with N repeats with a given delay between them. CronTrigger s allow scheduling based on time of day, day of week, day of month, and month of year.
Job s and Trigger s have a name and group associated with them, which should uniquely identify them within a single Scheduler. The 'group' feature may be useful for creating logical groupings or categorizations of Jobs s and Triggerss. If you don't have need for assigning a group to a given Jobs of Triggers, then you can use the DEFAULT_GROUP constant defined on this interface.
Stored Job s can also be 'manually' triggered through the use of the triggerJob(String jobName, String jobGroup) function.
Client programs may also be interested in the 'listener' interfaces that are available from Quartz. The JobListener interface provides notifications of Job executions. The TriggerListener interface provides notifications of Trigger firings. The SchedulerListener interface provides notifications of Scheduler events and errors. Listeners can be associated with local schedulers through the ListenerManager interface.
The setup/configuration of a Scheduler instance is very customizable. Please consult the documentation distributed with Quartz.



## start


1. init SchedulerFactoryBean
   
3. init SchedulerFactory

4. create ThreadPool

3. start SchedulerFactoryBean
1. ClusterManager

2. MisfireHandler: misfire tasks

3. set QuartzSchedulerThread paused=false


## Spring Boot
If Quartz is available, a Scheduler is auto-configured (through the SchedulerFactoryBean abstraction).

extends QuartzJobBean
```java

package org.springframework.scheduling.quartz;

public abstract class QuartzJobBean implements Job {
 
    public final void execute(JobExecutionContext context) throws JobExecutionException {
        try {
            BeanWrapper bw = PropertyAccessorFactory.forBeanPropertyAccess(this);
            MutablePropertyValues pvs = new MutablePropertyValues();
            pvs.addPropertyValues(context.getScheduler().getContext());
            pvs.addPropertyValues(context.getMergedJobDataMap());
            bw.setPropertyValues(pvs, true);
        } catch (SchedulerException var4) {
            throw new JobExecutionException(var4);
        }

        this.executeInternal(context);
    }

    protected abstract void executeInternal(JobExecutionContext var1) throws JobExecutionException;
}
```

## Cluster
Quartz’s clustering features bring both high availability and scalability to your scheduler via fail-over and load balancing functionality.

- **Depends on DB** Clustering currently only works with the JDBC-Jobstore (JobStoreTX or JobStoreCMT), and essentially works by having each node of the cluster share the same database.

- **Load-balancing** occurs automatically, with each node of the cluster firing jobs as quickly as it can. When a trigger’s firing time occurs, the first node to acquire it (**by placing a lock on it**) is the node that will fire it.

- **Exclusive** Only one node will fire the job for each firing. It won’t necessarily be the same node each time - it will more or less be random which node runs it. The load balancing mechanism is near-random for busy schedulers (lots of triggers) but favors the same node for non-busy (e.g. few triggers) schedulers.

- **Fail-over** occurs when one of the nodes fails while in the midst of executing one or more jobs. When a node fails, the other nodes detect the condition and identify the jobs in the database that were in progress within the failed node. Any jobs marked for recovery (with the "requests recovery" property on the JobDetail) will be re-executed by the remaining nodes. Jobs not marked for recovery will simply be freed up for execution at the next time a related trigger fires.

- **Partition** The clustering feature works best for scaling out **long-running and/or cpu-intensive jobs (distributing the work-load over multiple nodes)**. If you need to scale out to support thousands of short-running (e.g 1 second) jobs, consider partitioning the set of jobs by using multiple distinct schedulers (including multiple clustered schedulers for HA). The scheduler makes use of a cluster-wide lock, a pattern that degrades performance as you add more nodes (when going beyond about three nodes - depending upon your database’s capabilities, etc.).

Enable clustering by setting the "org.quartz.jobStore.isClustered" property to "true". Each instance in the cluster should use the same copy of the quartz.properties file. Exceptions of this would be to use properties files that are identical, with the following allowable exceptions: Different thread pool size, and different value for the "org.quartz.scheduler.instanceId" property. Each node in the cluster MUST have a unique instanceId, which is easily done (without needing different properties files) by placing "AUTO" as the value of this property. See the info about the configuration properties of JDBC-JobStore for more information.

**NOTE:** Never run clustering on separate machines, unless their clocks are synchronized using some form of time-sync service (daemon) that runs very regularly (the clocks must be within a second of each other). See https://www.nist.gov/pml/time-and-frequency-division/services/internet-time-service-its if you are unfamiliar with how to do this.

**NOTE:** Never start (scheduler.start()) a non-clustered instance against the same set of database tables that any other instance is running (start()ed) against. You may get serious data corruption, and will definitely experience erratic behavior.


### Example

```groovy
// build.gradle
implementation 'org.springframework.boot:spring-boot-starter-quartz'
implementation 'org.springframework.boot:spring-boot-starter-jdbc'
implementation group: 'mysql', name: 'mysql-connector-java', version: '8.0.25'
```

In particular, an Executor bean is not associated with the scheduler as Quartz offers a way to configure the scheduler via `spring.quartz.properties`.

```properties
spring.quartz.job-store-type=jdbc
# always run SQL to overwrite DB
spring.quartz.jdbc.initialize-schema=always
spring.datasource.url=jdbc:mysql://xxx.xxx.xxx.xxx/quartz?useUnicode=true&characterEncoding=utf8
spring.datasource.password=****
spring.datasource.username=xxx
```




## References
1. [Quartz Configuration Reference](http://www.quartz-scheduler.org/documentation/2.4.0-SNAPSHOT/configuration.html)
2. [Spring Boot - Quartz Scheduler](https://docs.spring.io/spring-boot/docs/current/reference/html/features.html#features.quartz)