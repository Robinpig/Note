



Metaspace is memory the VM uses to store class metadata.
Class metadata are the runtime representation of java classes within a JVM process - basically any information the JVM needs to work with a Java class. That includes, but is not limited to, runtime representation of data from the JVM class file format.
Examples:
● the “Klass” structure - the VM-internal representation of runtime state of a java class. This includes both vtable and itable.
● Method metadata - runtime equivalent of the method_info in the class file, containing things like the bytecode, exception table, constants, etc.
● The constant pool
● Annotations
● method counters collected at runtime as a base for JIT decisions
● etc.




Allocation from Metaspace is coupled to class loading. When a class is loaded and its runtime representation in the JVM is being prepared, Metaspace is allocated by its class loader to store the class’ metadata.
The allocated Metaspace for a class is owned by its class loader. It is only released when that class loader itself is unloaded, not before.
However, “releasing Metaspace” does not necessarily mean that memory is returned to the OS.
All or a part of that memory may be retained within the JVM; it may be reused for future class loading, but at the moment it remains unused within the JVM process.



There are two parameters to limit Metaspace size:
● -XX:MaxMetaspaceSize determines the maximum committed size the Metaspace is allowed to grow. It is by default unlimited.
● -XX:CompressedClassSpaceSize determines the virtual size of one important portion of the Metaspace, the Compressed Class Space. Its default value is 1G (note: reserved space, not committed



## Architecture

Metaspace is implemented in layers.
At the bottom, memory is allocated in large regions from the OS. At the middle, we carve those regions in not-so-large chunks and hand them over to class loaders. At the top, the class loaders cut up those chunks to serve the caller code.



排查metaspace OOM








