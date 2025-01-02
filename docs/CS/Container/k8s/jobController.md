## Introduction


入口函数 `cmd/kube-controller-manager/app/batch.go`

```c
func startJobController(ctx context.Context, controllerContext ControllerContext, controllerName string) (controller.Interface, bool, error) {
    jobController, err := job.NewController(
        ctx,
        controllerContext.InformerFactory.Core().V1().Pods(),
        controllerContext.InformerFactory.Batch().V1().Jobs(),
        controllerContext.ClientBuilder.ClientOrDie("job-controller"),
    )
    if err != nil {
        return nil, true, fmt.Errorf("creating Job controller: %v", err)
    }
    go jobController.Run(ctx, int(controllerContext.ComponentConfig.JobController.ConcurrentJobSyncs))
    return nil, true, nil
}
```

NewController creates a new Job controller that keeps the relevant pods in sync with their corresponding Job objects.

```c
// pkg/controller/job/job_controller.go
func NewController(ctx context.Context, podInformer coreinformers.PodInformer, jobInformer batchinformers.JobInformer, kubeClient clientset.Interface) (*Controller, error) {
    return newControllerWithClock(ctx, podInformer, jobInformer, kubeClient, &clock.RealClock{})
}

func newControllerWithClock(ctx context.Context, podInformer coreinformers.PodInformer, jobInformer batchinformers.JobInformer, kubeClient clientset.Interface, clock clock.WithTicker) (*Controller, error) {
    eventBroadcaster := record.NewBroadcaster(record.WithContext(ctx))
    logger := klog.FromContext(ctx)

    jm := &Controller{
        kubeClient: kubeClient,
        podControl: controller.RealPodControl{
            KubeClient: kubeClient,
            Recorder:   eventBroadcaster.NewRecorder(scheme.Scheme, v1.EventSource{Component: "job-controller"}),
        },
        expectations:          controller.NewControllerExpectations(),
        finalizerExpectations: newUIDTrackingExpectations(),
        queue:                 workqueue.NewTypedRateLimitingQueueWithConfig(workqueue.NewTypedItemExponentialFailureRateLimiter[string](DefaultJobApiBackOff, MaxJobApiBackOff), workqueue.TypedRateLimitingQueueConfig[string]{Name: "job", Clock: clock}),
        orphanQueue:           workqueue.NewTypedRateLimitingQueueWithConfig(workqueue.NewTypedItemExponentialFailureRateLimiter[string](DefaultJobApiBackOff, MaxJobApiBackOff), workqueue.TypedRateLimitingQueueConfig[string]{Name: "job_orphan_pod", Clock: clock}),
        broadcaster:           eventBroadcaster,
        recorder:              eventBroadcaster.NewRecorder(scheme.Scheme, v1.EventSource{Component: "job-controller"}),
        clock:                 clock,
        podBackoffStore:       newBackoffStore(),
    }

    if _, err := jobInformer.Informer().AddEventHandler(cache.ResourceEventHandlerFuncs{
        AddFunc: func(obj interface{}) {
            jm.addJob(logger, obj)
        },
        UpdateFunc: func(oldObj, newObj interface{}) {
            jm.updateJob(logger, oldObj, newObj)
        },
        DeleteFunc: func(obj interface{}) {
            jm.deleteJob(logger, obj)
        },
    }); err != nil {
        return nil, fmt.Errorf("adding Job event handler: %w", err)
    }
    jm.jobLister = jobInformer.Lister()
    jm.jobStoreSynced = jobInformer.Informer().HasSynced

    if _, err := podInformer.Informer().AddEventHandler(cache.ResourceEventHandlerFuncs{
        AddFunc: func(obj interface{}) {
            jm.addPod(logger, obj)
        },
        UpdateFunc: func(oldObj, newObj interface{}) {
            jm.updatePod(logger, oldObj, newObj)
        },
        DeleteFunc: func(obj interface{}) {
            jm.deletePod(logger, obj, true)
        },
    }); err != nil {
        return nil, fmt.Errorf("adding Pod event handler: %w", err)
    }
    jm.podStore = podInformer.Lister()
    jm.podStoreSynced = podInformer.Informer().HasSynced

    jm.updateStatusHandler = jm.updateJobStatus
    jm.patchJobHandler = jm.patchJob
    jm.syncHandler = jm.syncJob

    metrics.Register()

    return jm, nil
}
```

addJob
```c
func (jm *Controller) addJob(logger klog.Logger, obj interface{}) {
    jm.enqueueSyncJobImmediately(logger, obj)
    jobObj, ok := obj.(*batch.Job)
    if !ok {
        return
    }
    if controllerName := managedByExternalController(jobObj); controllerName != nil {
        metrics.JobByExternalControllerTotal.WithLabelValues(*controllerName).Inc()
    }
}

func (jm *Controller) enqueueSyncJobImmediately(logger klog.Logger, obj interface{}) {
	jm.enqueueSyncJobInternal(logger, obj, 0)
}

```


```c
func (jm *Controller) updateJob(logger klog.Logger, old, cur interface{}) {
    oldJob := old.(*batch.Job)
    curJob := cur.(*batch.Job)

    // never return error
    key, err := controller.KeyFunc(curJob)
    if err != nil {
        return
    }

    if curJob.Generation == oldJob.Generation {
        // Delay the Job sync when no generation change to batch Job status updates,
        // typically triggered by pod events.
        jm.enqueueSyncJobBatched(logger, curJob)
    } else {
        // Trigger immediate sync when spec is changed.
        jm.enqueueSyncJobImmediately(logger, curJob)
    }

    // The job shouldn't be marked as finished until all pod finalizers are removed.
    // This is a backup operation in this case.
    if util.IsJobFinished(curJob) {
        jm.cleanupPodFinalizers(curJob)
    }

    // check if need to add a new rsync for ActiveDeadlineSeconds
    if curJob.Status.StartTime != nil {
        curADS := curJob.Spec.ActiveDeadlineSeconds
        if curADS == nil {
            return
        }
        oldADS := oldJob.Spec.ActiveDeadlineSeconds
        if oldADS == nil || *oldADS != *curADS {
            passed := jm.clock.Since(curJob.Status.StartTime.Time)
            total := time.Duration(*curADS) * time.Second
            // AddAfter will handle total < passed
            jm.queue.AddAfter(key, total-passed)
            logger.V(4).Info("job's ActiveDeadlineSeconds updated, will rsync", "key", key, "interval", total-passed)
        }
    }
}
```



```c
func (jm *Controller) enqueueSyncJobInternal(logger klog.Logger, obj interface{}, delay time.Duration) {
	key, err := controller.KeyFunc(obj)
	if err != nil {
		utilruntime.HandleError(fmt.Errorf("Couldn't get key for object %+v: %v", obj, err))
		return
	}

	// TODO: Handle overlapping controllers better. Either disallow them at admission time or
	// deterministically avoid syncing controllers that fight over pods. Currently, we only
	// ensure that the same controller is synced for a given pod. When we periodically relist
	// all controllers there will still be some replica instability. One way to handle this is
	// by querying the store for all controllers that this rc overlaps, as well as all
	// controllers that overlap this rc, and sorting them.
	logger.Info("enqueueing job", "key", key, "delay", delay)
	jm.queue.AddAfter(key, delay)
}
```


addPod


```c
// When a pod is created, enqueue the controller that manages it and update its expectations.
func (jm *Controller) addPod(logger klog.Logger, obj interface{}) {
    pod := obj.(*v1.Pod)
    recordFinishedPodWithTrackingFinalizer(nil, pod)
    if pod.DeletionTimestamp != nil {
        // on a restart of the controller, it's possible a new pod shows up in a state that
        // is already pending deletion. Prevent the pod from being a creation observation.
        jm.deletePod(logger, pod, false)
        return
    }

    // If it has a ControllerRef, that's all that matters.
    if controllerRef := metav1.GetControllerOf(pod); controllerRef != nil {
        job := jm.resolveControllerRef(pod.Namespace, controllerRef)
        if job == nil {
            return
        }
        jobKey, err := controller.KeyFunc(job)
        if err != nil {
            return
        }
        jm.expectations.CreationObserved(logger, jobKey)
        jm.enqueueSyncJobBatched(logger, job)
        return
    }

    // Otherwise, it's an orphan.
    // Clean the finalizer.
    if hasJobTrackingFinalizer(pod) {
        jm.enqueueOrphanPod(pod)
    }
    // Get a list of all matching controllers and sync
    // them to see if anyone wants to adopt it.
    // DO NOT observe creation because no controller should be waiting for an
    // orphan.
    for _, job := range jm.getPodJobs(pod) {
        jm.enqueueSyncJobBatched(logger, job)
    }
}

// When a pod is updated, figure out what job/s manage it and wake them up.
// If the labels of the pod have changed we need to awaken both the old
// and new job. old and cur must be *v1.Pod types.
func (jm *Controller) updatePod(logger klog.Logger, old, cur interface{}) {
    curPod := cur.(*v1.Pod)
    oldPod := old.(*v1.Pod)
    recordFinishedPodWithTrackingFinalizer(oldPod, curPod)
    if curPod.ResourceVersion == oldPod.ResourceVersion {
        // Periodic resync will send update events for all known pods.
        // Two different versions of the same pod will always have different RVs.
        return
    }
    if curPod.DeletionTimestamp != nil {
        // when a pod is deleted gracefully it's deletion timestamp is first modified to reflect a grace period,
        // and after such time has passed, the kubelet actually deletes it from the store. We receive an update
        // for modification of the deletion timestamp and expect an job to create more pods asap, not wait
        // until the kubelet actually deletes the pod.
        jm.deletePod(logger, curPod, false)
        return
    }

    // Don't check if oldPod has the finalizer, as during ownership transfer
    // finalizers might be re-added and removed again in behalf of the new owner.
    // If all those Pod updates collapse into a single event, the finalizer
    // might be removed in oldPod and curPod. We want to record the latest
    // state.
    finalizerRemoved := !hasJobTrackingFinalizer(curPod)
    curControllerRef := metav1.GetControllerOf(curPod)
    oldControllerRef := metav1.GetControllerOf(oldPod)
    controllerRefChanged := !reflect.DeepEqual(curControllerRef, oldControllerRef)
    if controllerRefChanged && oldControllerRef != nil {
        // The ControllerRef was changed. Sync the old controller, if any.
        if job := jm.resolveControllerRef(oldPod.Namespace, oldControllerRef); job != nil {
            if finalizerRemoved {
                key, err := controller.KeyFunc(job)
                if err == nil {
                    jm.finalizerExpectations.finalizerRemovalObserved(logger, key, string(curPod.UID))
                }
            }
            jm.enqueueSyncJobBatched(logger, job)
        }
    }

    // If it has a ControllerRef, that's all that matters.
    if curControllerRef != nil {
        job := jm.resolveControllerRef(curPod.Namespace, curControllerRef)
        if job == nil {
            return
        }
        if finalizerRemoved {
            key, err := controller.KeyFunc(job)
            if err == nil {
                jm.finalizerExpectations.finalizerRemovalObserved(logger, key, string(curPod.UID))
            }
        }
        jm.enqueueSyncJobBatched(logger, job)
        return
    }

    // Otherwise, it's an orphan.
    // Clean the finalizer.
    if hasJobTrackingFinalizer(curPod) {
        jm.enqueueOrphanPod(curPod)
    }
    // If anything changed, sync matching controllers
    // to see if anyone wants to adopt it now.
    labelChanged := !reflect.DeepEqual(curPod.Labels, oldPod.Labels)
    if labelChanged || controllerRefChanged {
        for _, job := range jm.getPodJobs(curPod) {
            jm.enqueueSyncJobBatched(logger, job)
        }
    }
}
```

## Run

```c
// pkg/controller/job/job_controller.go
func (jm *Controller) Run(ctx context.Context, workers int) {
    defer utilruntime.HandleCrash()
    logger := klog.FromContext(ctx)

    // Start events processing pipeline.
    jm.broadcaster.StartStructuredLogging(3)
    jm.broadcaster.StartRecordingToSink(&v1core.EventSinkImpl{Interface: jm.kubeClient.CoreV1().Events("")})
    defer jm.broadcaster.Shutdown()

    defer jm.queue.ShutDown()
    defer jm.orphanQueue.ShutDown()

    logger.Info("Starting job controller")
    defer logger.Info("Shutting down job controller")

    if !cache.WaitForNamedCacheSync("job", ctx.Done(), jm.podStoreSynced, jm.jobStoreSynced) {
        return
    }

    for i := 0; i < workers; i++ {
        go wait.UntilWithContext(ctx, jm.worker, time.Second)
    }

    go wait.UntilWithContext(ctx, jm.orphanWorker, time.Second)

    <-ctx.Done()
}
```




worker


```c
// worker runs a worker thread that just dequeues items, processes them, and marks them done.
// It enforces that the syncHandler is never invoked concurrently with the same key.
func (jm *Controller) worker(ctx context.Context) {
    for jm.processNextWorkItem(ctx) {
    }
}

func (jm *Controller) processNextWorkItem(ctx context.Context) bool {
    key, quit := jm.queue.Get()
    if quit {
        return false
    }
    defer jm.queue.Done(key)

    err := jm.syncHandler(ctx, key)
    if err == nil {
        jm.queue.Forget(key)
        return true
    }

    utilruntime.HandleError(fmt.Errorf("syncing job: %w", err))
    jm.queue.AddRateLimited(key)

    return true
}
```

syncHandler 在 newControllerWithClock 已经赋值为 syncJob函数


```c
// syncJob will sync the job with the given key if it has had its expectations fulfilled, meaning
// it did not expect to see any more of its pods created or deleted. This function is not meant to be invoked
// concurrently with the same key.
func (jm *Controller) syncJob(ctx context.Context, key string) (rErr error) {
    startTime := jm.clock.Now()
    logger := klog.FromContext(ctx)
    defer func() {
        logger.V(4).Info("Finished syncing job", "key", key, "elapsed", jm.clock.Since(startTime))
    }()

    ns, name, err := cache.SplitMetaNamespaceKey(key)
    if err != nil {
        return err
    }
    if len(ns) == 0 || len(name) == 0 {
        return fmt.Errorf("invalid job key %q: either namespace or name is missing", key)
    }
    sharedJob, err := jm.jobLister.Jobs(ns).Get(name)
    if err != nil {
        if apierrors.IsNotFound(err) {
            logger.V(4).Info("Job has been deleted", "key", key)
            jm.expectations.DeleteExpectations(logger, key)
            jm.finalizerExpectations.deleteExpectations(logger, key)

            err := jm.podBackoffStore.removeBackoffRecord(key)
            if err != nil {
                // re-syncing here as the record has to be removed for finished/deleted jobs
                return fmt.Errorf("error removing backoff record %w", err)
            }
            return nil
        }
        return err
    }

    // Skip syncing of the job it is managed by another controller.
    // We cannot rely solely on skipping of queueing such jobs for synchronization,
    // because it is possible a synchronization task is queued for a job, without
    // the managedBy field, but the job is quickly replaced by another job with
    // the field. Then, the syncJob might be invoked for a job with the field.
    if controllerName := managedByExternalController(sharedJob); controllerName != nil {
        logger.V(2).Info("Skip syncing the job as it is managed by an external controller", "key", key, "uid", sharedJob.UID, "controllerName", controllerName)
        return nil
    }

    // make a copy so we don't mutate the shared cache
    job := *sharedJob.DeepCopy()

    // if job was finished previously, we don't want to redo the termination
    if util.IsJobFinished(&job) {
        err := jm.podBackoffStore.removeBackoffRecord(key)
        if err != nil {
            // re-syncing here as the record has to be removed for finished/deleted jobs
            return fmt.Errorf("error removing backoff record %w", err)
        }
        return nil
    }

    if job.Spec.CompletionMode != nil && *job.Spec.CompletionMode != batch.NonIndexedCompletion && *job.Spec.CompletionMode != batch.IndexedCompletion {
        jm.recorder.Event(&job, v1.EventTypeWarning, "UnknownCompletionMode", "Skipped Job sync because completion mode is unknown")
        return nil
    }

    completionMode := getCompletionMode(&job)
    action := metrics.JobSyncActionReconciling

    defer func() {
        result := "success"
        if rErr != nil {
            result = "error"
        }

        metrics.JobSyncDurationSeconds.WithLabelValues(completionMode, result, action).Observe(jm.clock.Since(startTime).Seconds())
        metrics.JobSyncNum.WithLabelValues(completionMode, result, action).Inc()
    }()

    if job.Status.UncountedTerminatedPods == nil {
        job.Status.UncountedTerminatedPods = &batch.UncountedTerminatedPods{}
    }

    // Check the expectations of the job before counting active pods, otherwise a new pod can sneak in
    // and update the expectations after we've retrieved active pods from the store. If a new pod enters
    // the store after we've checked the expectation, the job sync is just deferred till the next relist.
    satisfiedExpectations := jm.expectations.SatisfiedExpectations(logger, key)

    pods, err := jm.getPodsForJob(ctx, &job)
    if err != nil {
        return err
    }
    activePods := controller.FilterActivePods(logger, pods)
    jobCtx := &syncJobCtx{
        job:                  &job,
        pods:                 pods,
        activePods:           activePods,
        ready:                countReadyPods(activePods),
        uncounted:            newUncountedTerminatedPods(*job.Status.UncountedTerminatedPods),
        expectedRmFinalizers: jm.finalizerExpectations.getExpectedUIDs(key),
    }
    if trackTerminatingPods(&job) {
        jobCtx.terminating = ptr.To(controller.CountTerminatingPods(pods))
    }
    active := int32(len(jobCtx.activePods))
    newSucceededPods, newFailedPods := getNewFinishedPods(jobCtx)
    jobCtx.succeeded = job.Status.Succeeded + int32(len(newSucceededPods)) + int32(len(jobCtx.uncounted.succeeded))
    jobCtx.failed = job.Status.Failed + int32(nonIgnoredFailedPodsCount(jobCtx, newFailedPods)) + int32(len(jobCtx.uncounted.failed))

    // Job first start. Set StartTime only if the job is not in the suspended state.
    if job.Status.StartTime == nil && !jobSuspended(&job) {
        now := metav1.NewTime(jm.clock.Now())
        job.Status.StartTime = &now
    }

    jobCtx.newBackoffRecord = jm.podBackoffStore.newBackoffRecord(key, newSucceededPods, newFailedPods)

    var manageJobErr error

    exceedsBackoffLimit := jobCtx.failed > *job.Spec.BackoffLimit
    jobCtx.finishedCondition = hasSuccessCriteriaMetCondition(&job)

    // Given that the Job already has the SuccessCriteriaMet condition, the termination condition already had confirmed in another cycle.
    // So, the job-controller evaluates the podFailurePolicy only when the Job doesn't have the SuccessCriteriaMet condition.
    if jobCtx.finishedCondition == nil {
        failureTargetCondition := findConditionByType(job.Status.Conditions, batch.JobFailureTarget)
        if failureTargetCondition != nil && failureTargetCondition.Status == v1.ConditionTrue {
            jobCtx.finishedCondition = newFailedConditionForFailureTarget(failureTargetCondition, jm.clock.Now())
        } else if failJobMessage := getFailJobMessage(&job, pods); failJobMessage != nil {
            // Prepare the interim FailureTarget condition to record the failure message before the finalizers (allowing removal of the pods) are removed.
            jobCtx.finishedCondition = newCondition(batch.JobFailureTarget, v1.ConditionTrue, batch.JobReasonPodFailurePolicy, *failJobMessage, jm.clock.Now())
        }
    }
    if jobCtx.finishedCondition == nil {
        if exceedsBackoffLimit || pastBackoffLimitOnFailure(&job, pods) {
            // check if the number of pod restart exceeds backoff (for restart OnFailure only)
            // OR if the number of failed jobs increased since the last syncJob
            jobCtx.finishedCondition = jm.newFailureCondition(batch.JobReasonBackoffLimitExceeded, "Job has reached the specified backoff limit")
        } else if jm.pastActiveDeadline(&job) {
            jobCtx.finishedCondition = jm.newFailureCondition(batch.JobReasonDeadlineExceeded, "Job was active longer than specified deadline")
        } else if job.Spec.ActiveDeadlineSeconds != nil && !jobSuspended(&job) {
            syncDuration := time.Duration(*job.Spec.ActiveDeadlineSeconds)*time.Second - jm.clock.Since(job.Status.StartTime.Time)
            logger.V(2).Info("Job has activeDeadlineSeconds configuration. Will sync this job again", "key", key, "nextSyncIn", syncDuration)
            jm.queue.AddAfter(key, syncDuration)
        }
    }

    if isIndexedJob(&job) {
        jobCtx.prevSucceededIndexes, jobCtx.succeededIndexes = calculateSucceededIndexes(logger, &job, pods)
        jobCtx.succeeded = int32(jobCtx.succeededIndexes.total())
        if hasBackoffLimitPerIndex(&job) {
            jobCtx.failedIndexes = calculateFailedIndexes(logger, &job, pods)
            if jobCtx.finishedCondition == nil {
                if job.Spec.MaxFailedIndexes != nil && jobCtx.failedIndexes.total() > int(*job.Spec.MaxFailedIndexes) {
                    jobCtx.finishedCondition = jm.newFailureCondition(batch.JobReasonMaxFailedIndexesExceeded, "Job has exceeded the specified maximal number of failed indexes")
                } else if jobCtx.failedIndexes.total() > 0 && jobCtx.failedIndexes.total()+jobCtx.succeededIndexes.total() >= int(*job.Spec.Completions) {
                    jobCtx.finishedCondition = jm.newFailureCondition(batch.JobReasonFailedIndexes, "Job has failed indexes")
                }
            }
            jobCtx.podsWithDelayedDeletionPerIndex = getPodsWithDelayedDeletionPerIndex(logger, jobCtx)
        }
        if jobCtx.finishedCondition == nil {
            if msg, met := matchSuccessPolicy(logger, job.Spec.SuccessPolicy, *job.Spec.Completions, jobCtx.succeededIndexes); met {
                jobCtx.finishedCondition = newCondition(batch.JobSuccessCriteriaMet, v1.ConditionTrue, batch.JobReasonSuccessPolicy, msg, jm.clock.Now())
            }
        }
    }
    suspendCondChanged := false
    // Remove active pods if Job failed.
    if jobCtx.finishedCondition != nil {
        deletedReady, deleted, err := jm.deleteActivePods(ctx, &job, jobCtx.activePods)
        if deleted != active || !satisfiedExpectations {
            // Can't declare the Job as finished yet, as there might be remaining
            // pod finalizers or pods that are not in the informer's cache yet.
            jobCtx.finishedCondition = nil
        }
        active -= deleted
        if trackTerminatingPods(jobCtx.job) {
            *jobCtx.terminating += deleted
        }
        jobCtx.ready -= deletedReady
        manageJobErr = err
    } else {
        manageJobCalled := false
        if satisfiedExpectations && job.DeletionTimestamp == nil {
            active, action, manageJobErr = jm.manageJob(ctx, &job, jobCtx)
            manageJobCalled = true
        }
        complete := false
        if job.Spec.Completions == nil {
            // This type of job is complete when any pod exits with success.
            // Each pod is capable of
            // determining whether or not the entire Job is done.  Subsequent pods are
            // not expected to fail, but if they do, the failure is ignored.  Once any
            // pod succeeds, the controller waits for remaining pods to finish, and
            // then the job is complete.
            complete = jobCtx.succeeded > 0 && active == 0
        } else {
            // Job specifies a number of completions.  This type of job signals
            // success by having that number of successes.  Since we do not
            // start more pods than there are remaining completions, there should
            // not be any remaining active pods once this count is reached.
            complete = jobCtx.succeeded >= *job.Spec.Completions && active == 0
        }
        if complete {
            jobCtx.finishedCondition = jm.newSuccessCondition()
        } else if manageJobCalled {
            // Update the conditions / emit events only if manageJob was called in
            // this syncJob. Otherwise wait for the right syncJob call to make
            // updates.
            if job.Spec.Suspend != nil && *job.Spec.Suspend {
                // Job can be in the suspended state only if it is NOT completed.
                var isUpdated bool
                job.Status.Conditions, isUpdated = ensureJobConditionStatus(job.Status.Conditions, batch.JobSuspended, v1.ConditionTrue, "JobSuspended", "Job suspended", jm.clock.Now())
                if isUpdated {
                    suspendCondChanged = true
                    jm.recorder.Event(&job, v1.EventTypeNormal, "Suspended", "Job suspended")
                }
            } else {
                // Job not suspended.
                var isUpdated bool
                job.Status.Conditions, isUpdated = ensureJobConditionStatus(job.Status.Conditions, batch.JobSuspended, v1.ConditionFalse, "JobResumed", "Job resumed", jm.clock.Now())
                if isUpdated {
                    suspendCondChanged = true
                    jm.recorder.Event(&job, v1.EventTypeNormal, "Resumed", "Job resumed")
                    // Resumed jobs will always reset StartTime to current time. This is
                    // done because the ActiveDeadlineSeconds timer shouldn't go off
                    // whilst the Job is still suspended and resetting StartTime is
                    // consistent with resuming a Job created in the suspended state.
                    // (ActiveDeadlineSeconds is interpreted as the number of seconds a
                    // Job is continuously active.)
                    now := metav1.NewTime(jm.clock.Now())
                    job.Status.StartTime = &now
                }
            }
        }
    }

    var terminating *int32
    if feature.DefaultFeatureGate.Enabled(features.JobPodReplacementPolicy) {
        terminating = jobCtx.terminating
    }
    needsStatusUpdate := suspendCondChanged || active != job.Status.Active || !ptr.Equal(&jobCtx.ready, job.Status.Ready)
    needsStatusUpdate = needsStatusUpdate || !ptr.Equal(job.Status.Terminating, terminating)
    job.Status.Active = active
    job.Status.Ready = &jobCtx.ready
    job.Status.Terminating = terminating
    err = jm.trackJobStatusAndRemoveFinalizers(ctx, jobCtx, needsStatusUpdate)
    if err != nil {
        return fmt.Errorf("tracking status: %w", err)
    }

    return manageJobErr
}
```




```c
// manageJob is the core method responsible for managing the number of running
// pods according to what is specified in the job.Spec.
// Respects back-off; does not create new pods if the back-off time has not passed
// Does NOT modify <activePods>.
func (jm *Controller) manageJob(ctx context.Context, job *batch.Job, jobCtx *syncJobCtx) (int32, string, error) {
    logger := klog.FromContext(ctx)
    active := int32(len(jobCtx.activePods))
    parallelism := *job.Spec.Parallelism
    jobKey, err := controller.KeyFunc(job)
    if err != nil {
        utilruntime.HandleError(fmt.Errorf("Couldn't get key for job %#v: %v", job, err))
        return 0, metrics.JobSyncActionTracking, nil
    }

    if jobSuspended(job) {
        logger.V(4).Info("Deleting all active pods in suspended job", "job", klog.KObj(job), "active", active)
        podsToDelete := activePodsForRemoval(job, jobCtx.activePods, int(active))
        jm.expectations.ExpectDeletions(logger, jobKey, len(podsToDelete))
        removedReady, removed, err := jm.deleteJobPods(ctx, job, jobKey, podsToDelete)
        active -= removed
        if trackTerminatingPods(job) {
            *jobCtx.terminating += removed
        }
        jobCtx.ready -= removedReady
        return active, metrics.JobSyncActionPodsDeleted, err
    }

    wantActive := int32(0)
    if job.Spec.Completions == nil {
        // Job does not specify a number of completions.  Therefore, number active
        // should be equal to parallelism, unless the job has seen at least
        // once success, in which leave whatever is running, running.
        if jobCtx.succeeded > 0 {
            wantActive = active
        } else {
            wantActive = parallelism
        }
    } else {
        // Job specifies a specific number of completions.  Therefore, number
        // active should not ever exceed number of remaining completions.
        wantActive = *job.Spec.Completions - jobCtx.succeeded
        if wantActive > parallelism {
            wantActive = parallelism
        }
        if wantActive < 0 {
            wantActive = 0
        }
    }

    rmAtLeast := active - wantActive
    if rmAtLeast < 0 {
        rmAtLeast = 0
    }
    podsToDelete := activePodsForRemoval(job, jobCtx.activePods, int(rmAtLeast))
    if len(podsToDelete) > MaxPodCreateDeletePerSync {
        podsToDelete = podsToDelete[:MaxPodCreateDeletePerSync]
    }
    if len(podsToDelete) > 0 {
        jm.expectations.ExpectDeletions(logger, jobKey, len(podsToDelete))
        logger.V(4).Info("Too many pods running for job", "job", klog.KObj(job), "deleted", len(podsToDelete), "target", wantActive)
        removedReady, removed, err := jm.deleteJobPods(ctx, job, jobKey, podsToDelete)
        active -= removed
        if trackTerminatingPods(job) {
            *jobCtx.terminating += removed
        }
        jobCtx.ready -= removedReady
        // While it is possible for a Job to require both pod creations and
        // deletions at the same time (e.g. indexed Jobs with repeated indexes), we
        // restrict ourselves to either just pod deletion or pod creation in any
        // given sync cycle. Of these two, pod deletion takes precedence.
        return active, metrics.JobSyncActionPodsDeleted, err
    }

    var terminating int32 = 0
    if onlyReplaceFailedPods(jobCtx.job) {
        // When onlyReplaceFailedPods=true, then also trackTerminatingPods=true,
        // and so we can use the value.
        terminating = *jobCtx.terminating
    }
    if diff := wantActive - terminating - active; diff > 0 {
        var remainingTime time.Duration
        if !hasBackoffLimitPerIndex(job) {
            // we compute the global remaining time for pod creation when backoffLimitPerIndex is not used
            remainingTime = jobCtx.newBackoffRecord.getRemainingTime(jm.clock, DefaultJobPodFailureBackOff, MaxJobPodFailureBackOff)
        }
        if remainingTime > 0 {
            jm.enqueueSyncJobWithDelay(logger, job, remainingTime)
            return 0, metrics.JobSyncActionPodsCreated, nil
        }
        if diff > int32(MaxPodCreateDeletePerSync) {
            diff = int32(MaxPodCreateDeletePerSync)
        }

        var indexesToAdd []int
        if isIndexedJob(job) {
            indexesToAdd = firstPendingIndexes(jobCtx, int(diff), int(*job.Spec.Completions))
            if hasBackoffLimitPerIndex(job) {
                indexesToAdd, remainingTime = jm.getPodCreationInfoForIndependentIndexes(logger, indexesToAdd, jobCtx.podsWithDelayedDeletionPerIndex)
                if remainingTime > 0 {
                    jm.enqueueSyncJobWithDelay(logger, job, remainingTime)
                    return 0, metrics.JobSyncActionPodsCreated, nil
                }
            }
            diff = int32(len(indexesToAdd))
        }

        jm.expectations.ExpectCreations(logger, jobKey, int(diff))
        errCh := make(chan error, diff)
        logger.V(4).Info("Too few pods running", "key", jobKey, "need", wantActive, "creating", diff)

        wait := sync.WaitGroup{}

        active += diff

        podTemplate := job.Spec.Template.DeepCopy()
        if isIndexedJob(job) {
            addCompletionIndexEnvVariables(podTemplate)
        }
        podTemplate.Finalizers = appendJobCompletionFinalizerIfNotFound(podTemplate.Finalizers)

        // Counters for pod creation status (used by the job_pods_creation_total metric)
        var creationsSucceeded, creationsFailed int32 = 0, 0

        // Batch the pod creates. Batch sizes start at SlowStartInitialBatchSize
        // and double with each successful iteration in a kind of "slow start".
        // This handles attempts to start large numbers of pods that would
        // likely all fail with the same error. For example a project with a
        // low quota that attempts to create a large number of pods will be
        // prevented from spamming the API service with the pod create requests
        // after one of its pods fails.  Conveniently, this also prevents the
        // event spam that those failures would generate.
        for batchSize := min(diff, int32(controller.SlowStartInitialBatchSize)); diff > 0; batchSize = min(2*batchSize, diff) {
            errorCount := len(errCh)
            wait.Add(int(batchSize))
            for i := int32(0); i < batchSize; i++ {
                completionIndex := unknownCompletionIndex
                if len(indexesToAdd) > 0 {
                    completionIndex = indexesToAdd[0]
                    indexesToAdd = indexesToAdd[1:]
                }
                go func() {
                    template := podTemplate
                    generateName := ""
                    if completionIndex != unknownCompletionIndex {
                        template = podTemplate.DeepCopy()
                        addCompletionIndexAnnotation(template, completionIndex)

                        if feature.DefaultFeatureGate.Enabled(features.PodIndexLabel) {
                            addCompletionIndexLabel(template, completionIndex)
                        }
                        template.Spec.Hostname = fmt.Sprintf("%s-%d", job.Name, completionIndex)
                        generateName = podGenerateNameWithIndex(job.Name, completionIndex)
                        if hasBackoffLimitPerIndex(job) {
                            addIndexFailureCountAnnotation(logger, template, job, jobCtx.podsWithDelayedDeletionPerIndex[completionIndex])
                        }
                    }
                    defer wait.Done()
                    err := jm.podControl.CreatePodsWithGenerateName(ctx, job.Namespace, template, job, metav1.NewControllerRef(job, controllerKind), generateName)
                    if err != nil {
                        if apierrors.HasStatusCause(err, v1.NamespaceTerminatingCause) {
                            // If the namespace is being torn down, we can safely ignore
                            // this error since all subsequent creations will fail.
                            return
                        }
                    }
                    if err != nil {
                        defer utilruntime.HandleError(err)
                        // Decrement the expected number of creates because the informer won't observe this pod
                        logger.V(2).Info("Failed creation, decrementing expectations", "job", klog.KObj(job))
                        jm.expectations.CreationObserved(logger, jobKey)
                        atomic.AddInt32(&active, -1)
                        errCh <- err
                        atomic.AddInt32(&creationsFailed, 1)
                    }
                    atomic.AddInt32(&creationsSucceeded, 1)
                }()
            }
            wait.Wait()
            // any skipped pods that we never attempted to start shouldn't be expected.
            skippedPods := diff - batchSize
            if errorCount < len(errCh) && skippedPods > 0 {
                logger.V(2).Info("Slow-start failure. Skipping creating pods, decrementing expectations", "skippedCount", skippedPods, "job", klog.KObj(job))
                active -= skippedPods
                for i := int32(0); i < skippedPods; i++ {
                    // Decrement the expected number of creates because the informer won't observe this pod
                    jm.expectations.CreationObserved(logger, jobKey)
                }
                // The skipped pods will be retried later. The next controller resync will
                // retry the slow start process.
                break
            }
            diff -= batchSize
        }
        recordJobPodsCreationTotal(job, jobCtx, creationsSucceeded, creationsFailed)
        return active, metrics.JobSyncActionPodsCreated, errorFromChannel(errCh)
    }

    return active, metrics.JobSyncActionTracking, nil
}
```


- job 控制器启动后监听 job 增删改事件，和其他控制器一样，它监听到事件后并没有直接做操作，而是加入到队列里面，通过队列来实现多线程操作。
- 在入列的时候，immediate 参数为 true 则立即加入队列，否则根据失败次数计算退避时间再再次加入到延迟队列。
- 在更新 job 对象的时候，会计算 ActiveDeadlineSeconds 时间，如果对比上次更新多了 ActiveDeadlineSeconds 字段，则计算出延迟加入队列的时间再入列。
- job 控制器也引入了 pod 控制器，用来创建/删除/更新 pod 信息，这个 pod 控制器是再 controller_util 里面对 Clientset 操作 Pod 接口的再封装。
- 监听到 pod 事件时， 先判断 pod 是否处于删除状态，再判断 pod 是否属于 job 对象的，是的话，将 pod 的父对象加入队列，更新 job 对象的状态什么的。
- 我们注意到一直提到 ControllerExpectations 这个东西，这个按我目前的理解是类似于 sync.WaitGroup ，期望创建的 Pod 的数量为 N (等同于 sync.WaitGroup.Add(N) )，监视( SharedIndexInformer 的 Pod 的事件)到一个Pod创建成功就会通知 ControllerExpectations 对期望创建的 Pod 数量减一(等同于 sync.WaitGroup.Done() )
- 正是由于有 ControllerExpectations 这个的存在，syncJob 才能处理 job 对象看起来像在同步操作一样，直到期望达成才进入下一步的操作。
- manageJob 这里是控制 pod 数量的地方，多则删除，少则新增。








## Links

- [controller manager](/docs/CS/Container/k8s/controller-manager.md)