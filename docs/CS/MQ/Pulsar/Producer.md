## Introduction

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

## Links

- [Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md)
