## Introduction


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




