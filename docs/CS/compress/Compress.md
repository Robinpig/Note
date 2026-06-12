

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


## Links

- [CS](/docs/CS/CS.md)