## Introduction

SMTP is the principal application-layer protocol for Internet electronic mail. 
It uses the reliable data transfer service of [TCP](/docs/CS/CN/TCP.md) to transfer mail from the sender’s mail server to the recipient’s mail server. 


## Comparison with HTTP

Let’s now briefly compare SMTP with [HTTP](/docs/CS/CN/HTTP.md).


Both protocols are used to transfer files from one host to another: 
HTTP transfers files (also called objects) from a Web server to a Web client (typically a browser); 
SMTP transfers files (that is, e-mail messages) from one mail server to another mail server.
When transferring the files, both persistent HTTP and SMTP use persistent connections. 

However, there are important differences.

First, HTTP is mainly a pull protocol—someone loads information on a Web server and users use HTTP to pull the information from the server at their convenience. 
In particular, the TCP connection is initiated by the machine that wants to receive the file. 
On the other hand, SMTP is primarily a push protocol—the sending mail server pushes the file to the receiving mail server. 
In particular, the TCP connection is initiated by the machine that wants to send the file.

A second difference, which we alluded to earlier, is that SMTP requires each message, including the body of each message, to be in 7-bit ASCII format. 
If the message contains characters that are not 7-bit ASCII (for example, French characters with accents) or contains binary data (such as an image file), then the message has to be encoded into 7-bit ASCII. 
HTTP data does not impose this restriction.

A third important difference concerns how a document consisting of text and images (along with possibly other media types) is handled. 
HTTP encapsulates each object in its own HTTP response message. 
SMTP places all of the message’s objects into one message.


## POP3

## IMAP

## Web-Based E-Mail

With this service, the user agent is an ordinary Web browser, and the user communicates with its remote mailbox via HTTP.
When a recipient, such as Bob, wants to access a message in his mailbox, the e-mail message is sent from
Bob’s mail server to Bob’s browser using the HTTP protocol rather than the POP3 or IMAP protocol.
When a sender, such as Alice, wants to send an e-mail message, the e-mail message is sent from her browser to her mail server over HTTP rather than over SMTP. 
Alice’s mail server, however, still sends messages to, and receives messages from, other mail servers using SMTP.

## Links

- [Computer Network](/docs/CS/CN/CN.md)


## References

1. [RFC 5321 - Simple Mail Transfer Protocol](https://www.rfc-editor.org/info/rfc5321)
2. [RFC 1939 - Post Office Protocol - Version 3](https://www.rfc-editor.org/info/rfc1939)
3. [RFC 3501 - INTERNET MESSAGE ACCESS PROTOCOL - VERSION 4rev1](https://www.rfc-editor.org/info/rfc3501)