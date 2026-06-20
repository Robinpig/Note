## Introduction
Kafka's mirroring feature makes it possible to maintain a replica of an existing Kafka cluster. The following diagram shows how to use the _MirrorMaker_ tool to mirror a source Kafka cluster into a target (mirror) Kafka cluster. The tool uses a Kafka consumer to consume messages from the source cluster, and re-publishes those messages to the local (target) cluster using an embedded Kafka producer.




## References
1.  [Kafka mirroring (MirrorMaker)](https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=27846330)