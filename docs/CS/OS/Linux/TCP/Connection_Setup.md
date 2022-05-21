## Introduction


TCP connection involves a client and server side setup for the two ends to communicate.

The client has to make two systemcalls, socket() and connect(), to connect to the server. 
The server has to make arrangements to create a listening socket so that the client can generate request to connect to this socket. 
To make such an arrangement, the server has to make four systemcalls: socket(), bind(), listen(), and accept().

We will study the implementation of each systemcall in the kernel.

We saw what happens when we make a socket systemcall. 
We pass protocol family and type to socket(), and this does all the initial setup that involves initializing BSD and protocol socket operations. This involves initializing socket and sock structures. 

Now we need to do the rest of the work on the socket, which is already initialized by a call to socket() for client and server in different ways.

Now we will study the details of the kernel data structures associated with TCP connection setup on both client and server side.

The details of port allocation by the server when we call bind(). 
This also details how the conflicts are resolved when the server generates a request for specific port allocation. 
We will study the SYN queue design where the open connection request for the listening socket fi rst sits until the connection is completely established (three-way handshake is over). 

We will also see how the open connection request is moved from the SYN queue to the accept queue when the TCP connection is established.

Finally, we will see how the established connections are taken off the accept queue by making accept() call. 
Similarly, we will see how the client generates a connection request to the server (sends SYN segment to the listening server). 

In this chapter we will not cover the IP and link layer details (which will be discussed in later chapters) but will surely cover everything that is associated with the client – server connection setup in the kernel.

## Server Side Setup

- socket() systemcall only creates space for the socket in the kernel
- [bind()](/docs/CS/OS/Linux/Calls.md?id=bind) systemcall creates an identity for the socket and is the next step to create the server application
- Listen
- Accept


## Links

