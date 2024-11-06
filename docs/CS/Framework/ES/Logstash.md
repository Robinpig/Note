## Introduction

## Install


[Running Logstash on Docker](https://www.elastic.co/guide/en/logstash/current/docker.html)

logstash 在Docker时注意logstash.conf中es的地址无法使用localhost




docker run —rm -it —net elastic -v /Users/robin/Projects/elk/logstash/config/logstash.yml:/usr/share/logstash/config/logstash.yml -v /Users/robin/Projects/elk/logstash/config/logstash.conf:/usr/share/logstash/pipeline/logstash.conf  docker.elastic.co/logstash/logstash:8.15.3






## Links
- [ElasticSearch](/docs/CS/Framework/ES/ES.md)
