## Introduction

RPC is a communication mechanism between two parties, a *client* and a *server*.
In distributed computing, a remote procedure call (RPC) is when a computer program causes a procedure (subroutine) to execute in a different address space (commonly on another computer on a shared network),
which is coded as if it were a normal (local) procedure call, without the programmer explicitly coding the details for the remote interaction.

When the main program calls the procedure, what actually happens is that a call is made to a special procedure called the *client stub* on the client’s machine.
The client stub marshalls (collects) the parameters into a message, and then sends the message to the server machine where it is received by the *server stub*.
The server stub unpacks the parameters from the message, and then calls the server procedure using the standard calling sequence.
In this way, both the main program and the called procedure see only ordinary, local procedure calls, using the normal calling conventions.
Only the stubs, which are typically automatically generated by the compiler, know that the call is remote.
In particular, the programmer does not have to be aware of the network at all or the details of how message passing works.
The distribu- tion of the program over two machines is said to be **transparent**.
Furthermore, between RPCs, there is no connection of any kind established between the client and server.

## Conceptual Model

In this section we will deal with a variety of problems that are inherent in the RPC model of a client sending a message to a server then blocking until a reply is received.

### C/S Model

RPC is not appropriate to all computations. A a simple example of where it is not appropriate, consider a simple UNIX pipeline:

```shell
sort <infile | uniq | wc -l > outfile
```

It is hard to see who is the client and who is the server here.
One possible confi- guration would be to have each of the three programs act as both client and server at times, possibly split up into two processes internally if need be.

Having sort contain two processes, both clients, one talking to the file server to acquire data and one talking to uniq to pump data at it creates an asymmetric situation.
The first component of the pipeline then contains two clients and the rest one client and one server.
Various ad hoc solutions are possible, such as having the pipes be active processes that pull and push data where needed, but no matter how one looks at it, it is clear that the RPC model just does not fit.

### Thread Model

Another server design decision that RPC virtually forces on the operating system designer is the choice of a multi-threaded over a single threaded file server.

### The Two Army Problem

Consider what happens if a client requests a server to provide it with some irre- placeable data, for example, by sampling a real-time physics experiment being con- trolled by the server.
After sending its reply, the server cannot just discard the data because the reply may have been lost, in which case the client stub will time out and repeat the request.
The question is ‘‘How long should the server hold the irreplaceable data?’’

This problem, known as the two-army problem, also occurs in virtual circuit systems when trying to close a connection gracefully.


### Heterogeneous Machines

Another class of problems occurs if the client and server run on different kinds of computers. The ISO model handles most of these problems with the general mechanism of *option negotiation*.
When a virtual circuit is opened, the client can describe the relevant parameters of its machine, and ask the server to describe its parameters.
Then the two parties can negotiate and finally choose a set of parameters that both sides understand and can live with.
With transparent RPC, the client can hardly be expected to negotiate with its procedures concerning the parameters of the machine they are running on.

- Parameter Representation
- Byte Ordering
- Structure Alignment

## Technical

### Parameter Marshalling

In order to marshall the parameters, the client stub has to know how many there are and what type they all have.

For strongly typed languages, these usually does not cause any trouble, although if union types or variant records are permitted, the stub may not be able to deduce which union member or variant record is being passed.

For languages such as C, which are not type safe, the problems are worse.
The procedure printf, for example, is called with a variety of different parameters.
If printf or anything like it is the procedure to be called remotely, the client stub has no easy way of determining how many parameters there are or what there types are.

### Parameter Passing

When the client calls its stub, the call is made using the normal calling sequence.
The stub then collects the parameters and puts them into the message to be sent to the server.
If all the parameters are value parameters, no problem arises.
They are just copied into the message and off they go.

However, if there are reference parameters or pointers, things are more complicated.
While it is obviously possible to copy pointers into the message, when the server tries to use them, it will not work correctly because the object pointed to will not be present.

These are some of the questions made by the authors and you can easily see that it breaks the transparency characteristic that the RPC tries to provide.

### Global Variables

This is similar to the problem above with pointers and difficult in the same manner.

One might say: “don’t use global variables”.
This is one way to deal with this problem but the same way that happens with pointers, it breaks the transparency promise of RPC.

### Timing

## Abnormal Situations

### Exception Handling

When a procedure is executed locally it either completes or fails entirely. Remote procedures introduce new errors regarding the communication over the network and also when one party fails.

The problem here is the fact that RPC was sold with the transparency promise between local and remote calls.
It should be clear that the programmers must deal with new errors.

### Repeated Execution Semantics

For this topic it is important to distinguish two kinds of remote procedures, those that are idempotent and those that are not.

The framework can’t decide what to do in case one message is lost.
Facilities to deal with such problems are always welcome but in any case, it should be decided by the programmer developing the system.

### Loss of State

Even if a server crashes between RPCs and reboots itself before the next RPC occurs, serious problems can occur.

The programmers involved in the system should consider the possible failures and design the system to act accordingly in cases where a problem occurs.
It might lead them to avoid using RPC and that is fine, we don’t have a unique way for building distributed systems. Other options should always be considered.

### Orphans

So far we have only dealt with server crashes. Client crashes also pose problems.
If a client crashes while the server is still busy, the server’s computation has become an *orphan*.

Anyway, this is another problem that can’t be hidden from the programmers because it’s their job to decide about what to do in such cases.

## Performance

### Parallelism

With RPC, when the server is active, the client is always idle, waiting for the response.
Thus there is never any parallelism possible. The client and the server are effectively coroutines.
While the server is waiting for, say, a disk operation, all the clients have to wait.

Asynchronous methods also a better way in multi-threaded servers.

### Streaming

In data base work it is common for a client to request a server to perform an operation to look up tuples in a data base that meet some predicate.
With RPC, the server must wait until all the tuples have been found before making the reply.
If the operation of finding all the tuples is a time consuming one, the client may be idle for a long time waiting for the last tuple to be found.

Now [gRPC](/docs/CS/Distributed/RPC/grpc.md) and Finagle support to build stream clients and servers.

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed_Systems.md)

## References

1. [Remote Procedure Call](https://christophermeiklejohn.com/pl/2016/04/12/rpc.html)
2. [A Critique of the Remote Procedure Call Paradigm](https://www.win.tue.nl/~johanl/educ/2II45/2010/Lit/Tanenbaum%20RPC%2088.pdf)
3. [Procedure Call Protocol Documents，Version 2]()