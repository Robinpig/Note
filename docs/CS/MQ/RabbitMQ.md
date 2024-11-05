## Introduction


```shell
docker pull rabbitmq

docker run -d -p 15673:15672 -p 5674:5672 --restart=always -e RABBITMQ_DEFAULT_VHOST=my_vhost -e RABBITMQ_DEFAULT_USER=admin -e RABBITMQ_DEFAULT_PASS=admin123456 --hostname myRabbit --name rabbitmq-new rabbitmq:latest
```

Only Queue model

- A producer is a user application that sends messages.
- A queue is a buffer that stores messages.
- A consumer is a user application that receives messages.

The core idea in the messaging model in RabbitMQ is that the producer never sends any messages directly to a queue. 
Actually, quite often the producer doesn't even know if a message will be delivered to any queue at all.


Instead, the producer can only send messages to an exchange. An exchange is a very simple thing. 
On one side it receives messages from producers and on the other side it pushes them to queues. 
The exchange must know exactly what to do with a message it receives. 



## Links

- [MQ](/docs/CS/MQ/MQ.md?id=RocketMQ)




