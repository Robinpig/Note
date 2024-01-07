## Introduction

[Apache BookKeeper](https://bookkeeper.apache.org/) is a scalable, fault-tolerant, and low-latency storage service optimized for real-time workloads. It offers durability, replication, and strong consistency as essentials for building reliable real-time applications.

BookKeeper is suitable for a wide variety of use cases, including:



BookKeeper is a service that provides persistent storage of streams of log entries—aka records—in sequences called ledgers. BookKeeper replicates stored entries across multiple servers.

In BookKeeper:

- each unit of a log is an entry (aka record)
- streams of log entries are called ledgers
- individual servers storing ledgers of entries are called bookie

BookKeeper is designed to be reliable and resilient to a wide variety of failures. Bookies can crash, corrupt data, or discard data, but as long as there are enough bookies behaving correctly in the ensemble the service as a whole will behave correctly.



## Links
