## Introduction


listpack和ziplist的区别是element不像zentry一样保存prelen

ZipList 会有连锁更新的问题，最根本的原因就是因为 prevlen 的存在，当 ZipList 新增某个元素或修改某个元素时，如果空间不不够，压缩列表占用的内存空间就需要重新分配。而当新插入的元素较大时，可能会导致后续元素的 prevlen 占用空间都发生变化，从而引起连锁更新问题



## Links

- [Redis Struct](/docs/CS/DB/Redis/struct.md?id=lists)