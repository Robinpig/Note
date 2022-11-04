## Introduction




BrokerController

```java
public void start() throws Exception {

        this.shouldStartTime = System.currentTimeMillis() + messageStoreConfig.getDisappearTimeAfterStart();

        if (messageStoreConfig.getTotalReplicas() > 1 && this.brokerConfig.isEnableSlaveActingMaster() || this.brokerConfig.isEnableControllerMode()) {
            isIsolated = true;
        }

        if (this.brokerOuterAPI != null) {
            this.brokerOuterAPI.start();
        }

        startBasicService();

        if (!isIsolated && !this.messageStoreConfig.isEnableDLegerCommitLog() && !this.messageStoreConfig.isDuplicationEnable()) {
            changeSpecialServiceStatus(this.brokerConfig.getBrokerId() == MixAll.MASTER_ID);
            this.registerBrokerAll(true, false, true);
        }

        scheduledFutures.add(this.scheduledExecutorService.scheduleAtFixedRate(new AbstractBrokerRunnable(this.getBrokerIdentity()) {
            @Override
            public void run2() {
                try {
                    if (System.currentTimeMillis() < shouldStartTime) {
                        BrokerController.LOG.info(“Register to namesrv after {}”, shouldStartTime);
                        return;
                    }
                    if (isIsolated) {
                        BrokerController.LOG.info(“Skip register for broker is isolated”);
                        return;
                    }
                    // Send heartbeat
                    BrokerController.this.registerBrokerAll(true, false, brokerConfig.isForceRegister());
                } catch (Throwable e) {
                    BrokerController.LOG.error(“registerBrokerAll Exception”, e);
                }
            }
        }, 1000 * 10, Math.max(10000, Math.min(brokerConfig.getRegisterNameServerPeriod(), 60000)), TimeUnit.MILLISECONDS));

        if (this.brokerConfig.isEnableSlaveActingMaster()) {
            scheduleSendHeartbeat();

            scheduledFutures.add(this.syncBrokerMemberGroupExecutorService.scheduleAtFixedRate(new AbstractBrokerRunnable(this.getBrokerIdentity()) {
                @Override
                public void run2() {
                    try {
                        BrokerController.this.syncBrokerMemberGroup();
                    } catch (Throwable e) {
                        BrokerController.LOG.error(“sync BrokerMemberGroup error. “, e);
                    }
                }
            }, 1000, this.brokerConfig.getSyncBrokerMemberGroupPeriod(), TimeUnit.MILLISECONDS));
        }

        if (this.brokerConfig.isEnableControllerMode()) {
            scheduleSendHeartbeat();
        }

        if (brokerConfig.isSkipPreOnline()) {
            startServiceWithoutCondition();
        }
    }
```



Broker sync route table every 30s

PushConumser

Actually a pull

RebalanceService thread

pullRequestQueue

PullMessageProcessor of broker



## Links

- [RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)