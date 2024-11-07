## Introduction

As an asset, information needs to be secured from attacks.
To be secure, information needs to be hidden from unauthorized access (*confidentiality*), protected from unauthorized change(*integrity*), and available to an authorized entity when it is needed (*availability*).

### Attacks

In general, two types of attacks threaten the confidentiality of information: snooping and traffic analysis.

The integrity of data can be threatened by several kinds of attacks: modification, masquerading, replaying, and repudiation.

We mention only one attack threatening availability: *denial of service*.

### Services and techniques

ITU-T defines some security services to achieve security goals and prevent attacks.
Each of these services is designed to prevent one or more attacks while maintaining security goals. The actual implementation of security goals needs some techniques.
Two techniques are prevalent today: one is very general (cryptography) and one is specific (steganography).

#### Cryptography

Cryptography, a word with Greek origins, means ‘secret writing’. However, we use the term to refer to the science and art of transforming messages to make them secure and immune to attacks.
Although in the past cryptography referred only to the encryption and decryption of messages using secret keys, today it is defined as involving three distinct mechanisms: symmetric-key encipherment, asymmetric-key encipherment, and hashing.

#### Steganography

The word steganography, with origins in Greek, means ‘covered writing’, in contrast to cryptography, which means ‘secret writing’.
Cryptography means concealing the contents of a message by enciphering; steganography means concealing the message itself by covering it with something else.

### Confidentiality

Confidentiality can be achieved using ciphers. Ciphers can be divided into two broad categories: symmetric-key and asymmetric-key.

### Message integrity

One way to preserve the integrity of a document is through the use of a *fingerprint*.
To preserve the integrity of a message, the message is passed through an algorithm called a **cryptographic hash function**.
The function creates a compressed image of the message, called a digest, that can be used like a fingerprint.

> The message digest needs to be safe from change.

A MAC provides message integrity and message authentication using a combination of a hash function and a secret key.

### Digital signature

A digital signature uses a pair of private–public keys.

### 故障演练

故障模拟

故障主要分三类

- **中间件服务故障**，如模拟hsf调用方异常，tddl调用异常等。
- **机器故障**，如网络延迟，网络丢包等。
- **第三方故障**，如mysql响应延迟等。

故障演练的范围可以细化到应用，机房，甚至某个具体虚拟机。

参考alibaba Monkeyking


## Links

- [CS](/docs/CS/CS.md)
