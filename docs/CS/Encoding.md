## Introduction

There are several modes of dataflow, illustrating different scenarios in which data encodings are important:

- Databases, where the process writing to the database encodes the data and the process reading from the database decodes it

- RPC and REST APIs, where the client encodes a request, the server decodes the request and encodes a response, and the client finally decodes the response
- Asynchronous message passing (using message brokers or actors), where nodes communicate by sending each other messages that are encoded by the sender and decoded by the recipient

Applications inevitably change over time.
Features are added or modified as new products are launched, user requirements become better understood, or business circumstances change.

In particular, many services need to support rolling upgrades, where a new version of a service is gradually deployed to a few nodes at a time, rather than deploying to all nodes simultaneously.
Rolling upgrades allow new versions of a service to be released without downtime (thus encouraging frequent small releases over rare big releases) and make deployments less risky
(allowing faulty releases to be detected and rolled back before they affect a large number of users).
These properties are hugely beneficial for evolvability, the ease of making changes to an application.
During rolling upgrades, or for various other reasons, we must assume that different nodes are running the different versions of our application’s code.
Thus, it is important that all data flowing around the system is encoded in a way that provides backward compatibility (new code can read old data) and forward compatibility (old code can read new data).

We discussed several data encoding formats and their compatibility properties:

- Programming language–specific encodings are restricted to a single programming language and often fail to provide forward and backward compatibility.
- Textual formats like JSON, XML, and CSV are widespread, and their compatibility depends on how you use them.
  They have optional schema languages, which are sometimes helpful and sometimes a hindrance.
  These formats are somewhat vague about datatypes, so you have to be careful with things like numbers and binary strings.
- Binary schema–driven formats like Thrift, [Protocol Buffers](/docs/CS/Distributed/RPC/ProtoBuf.md), and Avro allow compact, efficient encoding with clearly defined forward and backward compatibility semantics.
  The schemas can be useful for documentation and code generation in statically typed languages.
  However, they have the downside that data needs to be decoded before it is human-readable.




### Language-Specific Formats

Many programming languages come with built-in support for encoding in-memory objects into byte sequences. 
For example, Java has java.io.Serializable, Ruby has Marshal, Python has pickle, and so on. 
Many third-party libraries also exist, such as Kryo for Java.
These encoding libraries are very convenient, because they allow in-memory objects to be saved and restored with minimal additional code. 
However, they also have a number of deep problems:
- The encoding is often tied to a particular programming language, and reading the data in another language is very difficult. 
  If you store or transmit data in such an encoding, you are committing yourself to your current programming language for potentially a very long time, and precluding integrating your systems with those of other organizations (which may use different languages).
- In order to restore data in the same object types, the decoding process needs to be able to instantiate arbitrary classes. 
  This is frequently a source of security problems: if an attacker can get your application to decode an arbitrary byte sequence, they can instantiate arbitrary classes, which in turn often allows them to do terrible things such as remotely executing arbitrary code.
- Versioning data is often an afterthought in these libraries: as they are intended for quick and easy encoding of data, they often neglect the inconvenient problems of forward and backward compatibility.
- Efficiency (CPU time taken to encode or decode, and the size of the encoded structure) is also often an afterthought. 
  For example, Java’s built-in serialization is notorious for its bad performance and bloated encoding.
  

For these reasons it’s generally a bad idea to use your language’s built-in encoding for anything other than very transient purposes.

### Textual Formats

JSON, XML, and CSV are textual formats, and thus somewhat human-readable(although the syntax is a popular topic of debate).
Besides the superficial syntactic issues, they also have some subtle problems:

- There is a lot of ambiguity around the encoding of numbers.
  In XML and CSV, you cannot distinguish between a number and a string that happens to consist of digits (except by referring to an external schema).
  JSON distinguishes strings and numbers, but it doesn’t distinguish integers and floating-point numbers, and it doesn’t specify a precision.
  This is a problem when dealing with large numbers; for example, integers greater than 253 cannot be exactly represented in an IEEE 754 double-precision floating-point number, so such numbers become inaccurate when parsed in a language that uses floating-point numbers (such as JavaScript).
  An example of numbers larger than 253 occurs on Twitter, which uses a 64-bit number to identify each tweet.
  The JSON returned by Twitter’s API includes tweet IDs twice, once as a JSON number and once as a decimal string, to work around the fact that the numbers are not correctly parsed by JavaScript applications.
- JSON and XML have good support for Unicode character strings (i.e., humanreadable text), but they don’t support binary strings (sequences of bytes without a character encoding).
  Binary strings are a useful feature, so people get around this limitation by encoding the binary data as text using Base64.
  The schema is then used to indicate that the value should be interpreted as Base64-encoded.
  This works, but it’s somewhat hacky and increases the data size by 33%.
- There is optional schema support for both XML and JSON.
  These schema languages are quite powerful, and thus quite complicated to learn and implement.
  Use of XML schemas is fairly widespread, but many JSON-based tools don’t bother using schemas.
  Since the correct interpretation of data (such as numbers and binary strings) depends on information in the schema, applications that don’t use XML/JSON schemas need to potentially hardcode the appropriate encoding/decoding logic instead.
- CSV does not have any schema, so it is up to the application to define the meaning of each row and column.
  If an application change adds a new row or column, you have to handle that change manually.
  CSV is also a quite vague format (what happens if a value contains a comma or a newline character?).
  Although its escaping rules have been formally specified, not all parsers implement them correctly.


### Binary Encoding

For data that is used only internally within your organization, there is less pressure to use a lowest-common-denominator encoding format.
For example, you could choose a format that is more compact or faster to parse. 
For a small dataset, the gains are negligible, but once you get into the terabytes, the choice of data format can have a big impact.





## Java

最好默认设置UUID, 在某些序列化场景(如Redis, Tair) 默认会使用Java 的Serial, 避免后续字段的增减影响到之前数据的读取




## JSON


fastjson在某些场景下会导致jvm crash

当多个对象存在循环引用时 GSON和Jackson会抛异常



## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed_Systems.md)
- [RPC](/docs/CS/Distributed/RPC/RPC.md)