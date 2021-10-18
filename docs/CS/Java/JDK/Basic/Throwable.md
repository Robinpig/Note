### Throwable Hierarchy

![Throwable](../images/Throwable.png)



**NullPointerException**

A null object invoke **non-static** method will throw NPE.

Use == or != compare null value or use **Optional** to avoid comparison.


Use exceptions only for exceptional conditions
- Exceptions are, as their name implies, to be used only for exceptional conditions; they should never be used for ordinary control flow.
- A well-designed API must not force its clients to use exceptions for ordinary control flow.

Use checked exceptions for recoverable conditions and runtime exceptions for programming errors
- use checked exceptions for conditions from which the caller can reasonably be expected to recover.
- Use runtime exceptions to indicate programming errors.

All of the unchecked throwables you implement should subclass `RuntimeException`.

Avoid unnecessary use of checked exceptions
Favor the use of standard exceptions
Throw exceptions appropriate to the abstraction  
Document all exceptions thrown by each method
- Always declare checked exceptions individually, and document precisely the conditions under which each one is thrown using the Javadoc `@throws` tag.
- Use the Javadoc `@throws` tag to document each exception that a method can throw, but do not use the throws keyword on unchecked exceptions.

Include failure-capture information in detail messages.
Strive for failure atomicity. Generally speaking, a failed method invocation should leave the object in the state that it was in prior to the invocation.
If you choose to ignore an exception, the catch block should contain a comment explaining why it is appropriate to do so, and the variable should be named ignored