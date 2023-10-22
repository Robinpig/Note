## Introduction


InfluxDB is an open source time series database written in Rust, using Apache Arrow, Apache Parquet, and Apache DataFusion as its foundational building blocks.
This latest version (3.x) of InfluxDB focuses on providing a real-time buffer for observational data of all kinds (metrics, events, logs, traces, etc.)
that is queryable via SQL or InfluxQL, and persisted in bulk to object storage as Parquet files, which other third-party systems can then use.
It is able to run either with a write ahead log or completely off object storage if the write ahead log is disabled
(in this mode of operation there is a potential window of data loss for any data buffered that has not yet been persisted to object store).



## Links

- [DataBases](/docs/CS/DB/DB.md)


## References
1.[influxdata](https://www.influxdata.com/)

