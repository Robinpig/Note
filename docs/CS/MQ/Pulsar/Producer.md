## Introduction

## send
send async

1. applyCompression
2. canAddToBatch
3. serializeAndSendMessage
```java
public class ProducerImpl<T> extends ProducerBase<T> implements TimerTask, ConnectionHandler.Connection {
    public void sendAsync(Message<?> message, SendCallback callback) {
        checkArgument(message instanceof MessageImpl);

        if (!isValidProducerState(callback, message.getSequenceId())) {
            return;
        }

        MessageImpl<?> msg = (MessageImpl<?>) message;
        MessageMetadata msgMetadata = msg.getMessageBuilder();
        ByteBuf payload = msg.getDataBuffer();
        int uncompressedSize = payload.readableBytes();

        if (!canEnqueueRequest(callback, message.getSequenceId(), uncompressedSize)) {
            return;
        }

        // If compression is enabled, we are compressing, otherwise it will simply use the same buffer
        ByteBuf compressedPayload = payload;
        boolean compressed = false;
        // Batch will be compressed when closed
        // If a message has a delayed delivery time, we'll always send it individually
        if (!isBatchMessagingEnabled() || msgMetadata.hasDeliverAtTime()) {
            compressedPayload = applyCompression(payload);
            compressed = true;

            // validate msg-size (For batching this will be check at the batch completion size)
            int compressedSize = compressedPayload.readableBytes();
            if (compressedSize > ClientCnx.getMaxMessageSize() && !this.conf.isChunkingEnabled()) {
                compressedPayload.release();
                String compressedStr = (!isBatchMessagingEnabled() && conf.getCompressionType() != CompressionType.NONE)
                        ? "Compressed"
                        : "";
                PulsarClientException.InvalidMessageException invalidMessageException = new PulsarClientException.InvalidMessageException(
                        format("The producer %s of the topic %s sends a %s message with %d bytes that exceeds %d bytes",
                                producerName, topic, compressedStr, compressedSize, ClientCnx.getMaxMessageSize()));
                completeCallbackAndReleaseSemaphore(uncompressedSize, callback, invalidMessageException);
                return;
            }
        }

        if (!msg.isReplicated() && msgMetadata.hasProducerName()) {
            PulsarClientException.InvalidMessageException invalidMessageException =
                    new PulsarClientException.InvalidMessageException(
                            format("The producer %s of the topic %s can not reuse the same message", producerName, topic), msg.getSequenceId());
            completeCallbackAndReleaseSemaphore(uncompressedSize, callback, invalidMessageException);
            compressedPayload.release();
            return;
        }

        if (!populateMessageSchema(msg, callback)) {
            compressedPayload.release();
            return;
        }

        // send in chunks
        int totalChunks = canAddToBatch(msg) ? 1
                : Math.max(1, compressedPayload.readableBytes()) / ClientCnx.getMaxMessageSize()
                + (Math.max(1, compressedPayload.readableBytes()) % ClientCnx.getMaxMessageSize() == 0 ? 0 : 1);
        // chunked message also sent individually so, try to acquire send-permits
        for (int i = 0; i < (totalChunks - 1); i++) {
            if (!canEnqueueRequest(callback, message.getSequenceId(), 0 /* The memory was already reserved */)) {
                client.getMemoryLimitController().releaseMemory(uncompressedSize);
                semaphoreRelease(i + 1);
                return;
            }
        }

        try {
            synchronized (this) {
                int readStartIndex = 0;
                long sequenceId;
                if (!msgMetadata.hasSequenceId()) {
                    sequenceId = msgIdGeneratorUpdater.getAndIncrement(this);
                    msgMetadata.setSequenceId(sequenceId);
                } else {
                    sequenceId = msgMetadata.getSequenceId();
                }
                String uuid = totalChunks > 1 ? String.format("%s-%d", producerName, sequenceId) : null;
                byte[] schemaVersion = totalChunks > 1 && msg.getMessageBuilder().hasSchemaVersion() ?
                        msg.getMessageBuilder().getSchemaVersion() : null;
                byte[] orderingKey = totalChunks > 1 && msg.getMessageBuilder().hasOrderingKey() ?
                        msg.getMessageBuilder().getOrderingKey() : null;
                for (int chunkId = 0; chunkId < totalChunks; chunkId++) {
                    // Need to reset the schemaVersion, because the schemaVersion is based on a ByteBuf object in
                    // `MessageMetadata`, if we want to re-serialize the `SEND` command using a same `MessageMetadata`,
                    // we need to reset the ByteBuf of the schemaVersion in `MessageMetadata`, I think we need to
                    // reset `ByteBuf` objects in `MessageMetadata` after call the method `MessageMetadata#writeTo()`.
                    if (chunkId > 0) {
                        if (schemaVersion != null) {
                            msg.getMessageBuilder().setSchemaVersion(schemaVersion);
                        }
                        if (orderingKey != null) {
                            msg.getMessageBuilder().setOrderingKey(orderingKey);
                        }
                    }
                    serializeAndSendMessage(msg, payload, sequenceId, uuid, chunkId, totalChunks,
                            readStartIndex, ClientCnx.getMaxMessageSize(), compressedPayload, compressed,
                            compressedPayload.readableBytes(), uncompressedSize, callback);
                    readStartIndex = ((chunkId + 1) * ClientCnx.getMaxMessageSize());
                }
            }
        } catch (PulsarClientException e) {
            e.setSequenceId(msg.getSequenceId());
            completeCallbackAndReleaseSemaphore(uncompressedSize, callback, e);
        } catch (Throwable t) {
            completeCallbackAndReleaseSemaphore(uncompressedSize, callback, new PulsarClientException(t, msg.getSequenceId()));
        }
    }
}
```
#### serializeAndSendMessage

```java
public class ProducerImpl<T> extends ProducerBase<T> implements TimerTask, ConnectionHandler.Connection {
    private void serializeAndSendMessage(MessageImpl<?> msg, ByteBuf payload,
                                         long sequenceId, String uuid, int chunkId, int totalChunks, int readStartIndex, int chunkMaxSizeInBytes, ByteBuf compressedPayload,
                                         boolean compressed, int compressedPayloadSize,
                                         int uncompressedSize, SendCallback callback) throws IOException, InterruptedException {
        ByteBuf chunkPayload = compressedPayload;
        MessageMetadata msgMetadata = msg.getMessageBuilder();
        if (totalChunks > 1 && TopicName.get(topic).isPersistent()) {
            chunkPayload = compressedPayload.slice(readStartIndex,
                    Math.min(chunkMaxSizeInBytes, chunkPayload.readableBytes() - readStartIndex));
            // don't retain last chunk payload and builder as it will be not needed for next chunk-iteration and it will
            // be released once this chunk-message is sent
            if (chunkId != totalChunks - 1) {
                chunkPayload.retain();
            }
            if (uuid != null) {
                msgMetadata.setUuid(uuid);
            }
            msgMetadata.setChunkId(chunkId)
                    .setNumChunksFromMsg(totalChunks)
                    .setTotalChunkMsgSize(compressedPayloadSize);
        }
        if (!msgMetadata.hasPublishTime()) {
            msgMetadata.setPublishTime(client.getClientClock().millis());

            checkArgument(!msgMetadata.hasProducerName());

            msgMetadata.setProducerName(producerName);

            if (conf.getCompressionType() != CompressionType.NONE) {
                msgMetadata
                        .setCompression(CompressionCodecProvider.convertToWireProtocol(conf.getCompressionType()));
            }
            msgMetadata.setUncompressedSize(uncompressedSize);
        }

        if (canAddToBatch(msg) && totalChunks <= 1) {
            if (canAddToCurrentBatch(msg)) {
                // should trigger complete the batch message, new message will add to a new batch and new batch
                // sequence id use the new message, so that broker can handle the message duplication
                if (sequenceId <= lastSequenceIdPushed) {
                    isLastSequenceIdPotentialDuplicated = true;
                    if (sequenceId <= lastSequenceIdPublished) {
                        log.warn("Message with sequence id {} is definitely a duplicate", sequenceId);
                    } else {
                        log.info("Message with sequence id {} might be a duplicate but cannot be determined at this time.",
                                sequenceId);
                    }
                    doBatchSendAndAdd(msg, callback, payload);
                } else {
                    // Should flush the last potential duplicated since can't combine potential duplicated messages
                    // and non-duplicated messages into a batch.
                    if (isLastSequenceIdPotentialDuplicated) {
                        doBatchSendAndAdd(msg, callback, payload);
                    } else {
                        // handle boundary cases where message being added would exceed
                        // batch size and/or max message size
                        boolean isBatchFull = batchMessageContainer.add(msg, callback);
                        lastSendFuture = callback.getFuture();
                        payload.release();
                        if (isBatchFull) {
                            batchMessageAndSend();
                        }
                    }
                    isLastSequenceIdPotentialDuplicated = false;
                }
            } else {
                doBatchSendAndAdd(msg, callback, payload);
            }
        } else {
            // in this case compression has not been applied by the caller
            // but we have to compress the payload if compression is configured
            if (!compressed) {
                chunkPayload = applyCompression(chunkPayload);
            }
            ByteBuf encryptedPayload = encryptMessage(msgMetadata, chunkPayload);

            // When publishing during replication, we need to set the correct number of message in batch
            // This is only used in tracking the publish rate stats
            int numMessages = msg.getMessageBuilder().hasNumMessagesInBatch()
                    ? msg.getMessageBuilder().getNumMessagesInBatch()
                    : 1;
            final OpSendMsg op;
            if (msg.getSchemaState() == MessageImpl.SchemaState.Ready) {
                ByteBufPair cmd = sendMessage(producerId, sequenceId, numMessages, msgMetadata, encryptedPayload);
                op = OpSendMsg.create(msg, cmd, sequenceId, callback);
            } else {
                op = OpSendMsg.create(msg, null, sequenceId, callback);
                final MessageMetadata finalMsgMetadata = msgMetadata;
                op.rePopulate = () -> {
                    op.cmd = sendMessage(producerId, sequenceId, numMessages, finalMsgMetadata, encryptedPayload);
                };
            }
            op.setNumMessagesInBatch(numMessages);
            op.setBatchSizeByte(encryptedPayload.readableBytes());
            if (totalChunks > 1) {
                op.totalChunks = totalChunks;
                op.chunkId = chunkId;
            }
            lastSendFuture = callback.getFuture();
            processOpSendMsg(op);
        }
    }
}
```



```java

    protected void processOpSendMsg(OpSendMsg op) {
        if (op == null) {
            return;
        }
        try {
            if (op.msg != null && isBatchMessagingEnabled()) {
                batchMessageAndSend();
            }
            pendingMessages.add(op);
            if (op.msg != null) {
                LAST_SEQ_ID_PUSHED_UPDATER.getAndUpdate(this,
                        last -> Math.max(last, getHighestSequenceId(op)));
            }

            final ClientCnx cnx = getCnxIfReady();
            if (cnx != null) {
                if (op.msg != null && op.msg.getSchemaState() == None) {
                    tryRegisterSchema(cnx, op.msg, op.callback, this.connectionHandler.getEpoch());
                    return;
                }
                // If we do have a connection, the message is sent immediately, otherwise we'll try again once a new
                // connection is established
                op.cmd.retain();
                cnx.ctx().channel().eventLoop().execute(WriteInEventLoopCallback.create(this, cnx, op));
                stats.updateNumMsgsSent(op.numMessagesInBatch, op.batchSizeByte);
            } else {
                if (log.isDebugEnabled()) {
                    log.debug("[{}] [{}] Connection is not ready -- sequenceId {}", topic, producerName,
                        op.sequenceId);
                }
            }
        } catch (Throwable t) {
            releaseSemaphoreForSendOp(op);
            log.warn("[{}] [{}] error while closing out batch -- {}", topic, producerName, t);
            op.sendComplete(new PulsarClientException(t, op.sequenceId));
        }
    }
```


```java
public class ProducerImpl<T> extends ProducerBase<T> implements TimerTask, ConnectionHandler.Connection {
    @Override
    CompletableFuture<MessageId> internalSendWithTxnAsync(Message<?> message, Transaction txn) {
        if (txn == null) {
            return internalSendAsync(message);
        } else {
            CompletableFuture<MessageId> completableFuture = new CompletableFuture<>();
            if (!((TransactionImpl) txn).checkIfOpen(completableFuture)) {
                return completableFuture;
            }
            return ((TransactionImpl) txn).registerProducedTopic(topic)
                    .thenCompose(ignored -> internalSendAsync(message));
        }
    }


    @Override
    CompletableFuture<MessageId> internalSendAsync(Message<?> message) {
        CompletableFuture<MessageId> future = new CompletableFuture<>();

        MessageImpl<?> interceptorMessage = (MessageImpl) beforeSend(message);
        //Retain the buffer used by interceptors callback to get message. Buffer will release after complete interceptors.
        interceptorMessage.getDataBuffer().retain();
        if (interceptors != null) {
            interceptorMessage.getProperties();
        }
        sendAsync(interceptorMessage, new SendCallback() {
            SendCallback nextCallback = null;
            MessageImpl<?> nextMsg = null;
            long createdAt = System.nanoTime();

            @Override
            public CompletableFuture<MessageId> getFuture() {
                return future;
            }

            @Override
            public SendCallback getNextSendCallback() {
                return nextCallback;
            }

            @Override
            public MessageImpl<?> getNextMessage() {
                return nextMsg;
            }

            @Override
            public void sendComplete(Exception e) {
                try {
                    if (e != null) {
                        stats.incrementSendFailed();
                        onSendAcknowledgement(interceptorMessage, null, e);
                        future.completeExceptionally(e);
                    } else {
                        onSendAcknowledgement(interceptorMessage, interceptorMessage.getMessageId(), null);
                        future.complete(interceptorMessage.getMessageId());
                        stats.incrementNumAcksReceived(System.nanoTime() - createdAt);
                    }
                } finally {
                    interceptorMessage.getDataBuffer().release();
                }

                while (nextCallback != null) {
                    SendCallback sendCallback = nextCallback;
                    MessageImpl<?> msg = nextMsg;
                    //Retain the buffer used by interceptors callback to get message. Buffer will release after complete interceptors.
                    try {
                        msg.getDataBuffer().retain();
                        if (e != null) {
                            stats.incrementSendFailed();
                            onSendAcknowledgement(msg, null, e);
                            sendCallback.getFuture().completeExceptionally(e);
                        } else {
                            onSendAcknowledgement(msg, msg.getMessageId(), null);
                            sendCallback.getFuture().complete(msg.getMessageId());
                            stats.incrementNumAcksReceived(System.nanoTime() - createdAt);
                        }
                        nextMsg = nextCallback.getNextMessage();
                        nextCallback = nextCallback.getNextSendCallback();
                    } finally {
                        msg.getDataBuffer().release();
                    }
                }
            }

            @Override
            public void addCallback(MessageImpl<?> msg, SendCallback scb) {
                nextMsg = msg;
                nextCallback = scb;
            }
        });
        return future;
    }
}
```

### MessageRoutingMode




## Links

- [Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md)
