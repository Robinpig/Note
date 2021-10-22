## Introduction



[SUBSCRIBE](https://redis.io/commands/subscribe), [UNSUBSCRIBE](https://redis.io/commands/unsubscribe) and [PUBLISH](https://redis.io/commands/publish) implement the [Publish/Subscribe messaging paradigm](http://en.wikipedia.org/wiki/Publish/subscribe) where (citing Wikipedia) senders (publishers) are not programmed to send their messages to specific receivers (subscribers). Rather, published messages are characterized into channels, without knowledge of what (if any) subscribers there may be. Subscribers express interest in one or more channels, and only receive messages that are of interest, without knowledge of what (if any) publishers there are. This decoupling of publishers and subscribers can allow for greater scalability and a more dynamic network topology.

Please note that `redis-cli` will not accept any commands once in subscribed mode and can only quit the mode with `Ctrl-C`.


### Database & Scoping
Pub/Sub has no relation to the key space. It was made to not interfere with it on any level, including database numbers.

Publishing on db 10, will be heard by a subscriber on db 1.

If you need scoping of some kind, prefix the channels with the name of the environment (test, staging, production, ...).


## References
1. []()