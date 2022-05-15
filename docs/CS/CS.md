## Introduction

Number Systems


Data Storage


Operations on Data


Computer Organization

Computer Networks and Internet

Operating Systems

Algorithms

Programming Languages

Software Engineering

Databases

## Data Compression

Compressing data can reduce the amount of data to be sent or stored by partially eliminating inherent redundancy. Redundancy is created when we produce data. 
Through data compression, we make transmission and storage more efficient, and at the same time, we preserve the integrity of the data.

### Lossless Data Compression

In lossless data compression, the integrity of the data is preserved. 
The original data and the data after compression and decompression are exactly the same because, in these methods, the compression and decompression algorithms are exact inverses of each other: no part of the data is lost in the process. 
Redundant data is removed in compression and added during decompression.

Lossless compression methods are normally used when we cannot afford to lose any data. For example, we must not lose data when we compress a text file or an application program.

We discuss three lossless compression methods in this section: run-length encoding, Huffman coding, and the Lempel Ziv algorithm.


Run-length encoding is probably the simplest method of compression. It can be used to compress data made of any combination of symbols. 
It does not need to know the frequency of occurrence of symbols (as is necessary for Huffman coding) and can be very efficient if data is represented as 0s and 1s.


Huffman coding assigns shorter codes to symbols that occur more frequently and longer codes to those that occur less frequently.


Lempel Ziv (LZ) encoding, named after its inventors (Abraham Lempel and Jacob Ziv), is an example of a category of algorithms called dictionary-based encoding. 
The idea is to create a dictionary (a table) of strings used during the communication session. 
If both the sender and the receiver have a copy of the dictionary, then previously encountered strings can be substituted by their index in the dictionary to reduce the amount of information transmitted.

### Lossy Data Compression




## Security

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

## Theory of Computation







## The Turing Machine

A Turing machine is made of three components: a tape, a controller, and a read/write head.



The controller is the theoretical counterpart of the central processing unit (CPU) in modern computers. It is a finite state automaton, a machine that has a predetermined finite number of states and moves from one state to another based on the input. 
At any moment, it can be in one of these states.


> The Church–Turing Thesis
> 
> If an algorithm exists to do a symbol manipulation task, then a Turing machine exists to do that task.

Based on this claim, any symbol-manipulation task that can be done by writing an algorithm to do so can also be done by a Turing machine. 
Note that this is only a thesis, not a theorem. A theorem can be proved mathematically, a thesis cannot. Although this thesis probably can never be proved, there are strong arguments in its favor. 
- First, no algorithms have been found that cannot be simulated using a Turing machine. 
- Second, it has been proven that all computing models that have been mathematically proved are equivalent to the Turing machine model.


In theoretical computer science, an unsigned number is assigned to every program that can be written in a specific language. This is usually referred to as the Gödel number, named after the Austrian mathematician Kurt Gödel.


> The halting problem is unsolvable.


Complexity of solvable problems:

- Polynomial problems
- Non polynomial problems


## Artificial Intelligence

Artificial intelligence is the study of programmed systems that can simulate, to some extent, human activities such as perceiving, thinking, learning, and acting.


### The Turing test

In 1950, Alan Turing proposed the Turing Test, which provides a definition of intelligence in a machine. 
The test simply compares the intelligent behavior of a human being with that of a computer. 
An interrogator asks a set of questions that are forwarded to both a computer and a human being. 
The interrogator receives two sets of responses, but does not know which set comes from the human and which set from the computer. 
After careful examination of the two sets, if the interrogator cannot definitely tell which set has come from the computer and which from the human, the computer has passed the Turing test for intelligent behavior.


## References

1. [Foundations of Computer Science]()
