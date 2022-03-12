## Introduction




Some methods such as `ByteBuf.readBytes(int)` will cause a memory leak if the returned buffer is not released or added to the out List. 
Use derived buffers like `ByteBuf.readSlice(int)` to avoid leaking memory.