## Introduction

A hash is a mathematical function that converts an input of arbitrary length into an encrypted output of a fixed length. Thus regardless of the original amount of data or file size involved, its unique hash will always be the same size. Moreover, hashes cannot be used to "reverse-engineer" the input from the hashed output, since hash functions are "one-way" (like a meat grinder; you can't put the ground beef back into a steak). Still, if you use such a function on the same data, its hash will be identical, so you can validate that the data is the same (i.e., unaltered) if you already know its hash.



## func







## reslove conflict



- Open Addressing
- Separate Chaining
- rehash
- overflow table

### Separate Chaining

[HashMap in Java](/docs/CS/Java/JDK/Collection/Map.md?id=hash)





### Open Addressing



Like separate chaining, open addressing is a method for handling collisions. In Open Addressing, all elements are stored in the hash table itself. So at any point, the size of the table must be greater than or equal to the total number of keys (Note that we can increase table size by copying old data if needed). 

Insert(k): Keep probing until an empty slot is found. Once an empty slot is found, insert k. 

Search(k): Keep probing until slot’s key doesn’t become equal to k or an empty slot is reached. 

Delete(k): ***Delete operation is interesting***. If we simply delete a key, then the search may fail. So slots of deleted keys are marked specially as “deleted”. 
The insert can insert an item in a deleted slot, but the search doesn’t stop at a deleted slot. 





[ThreadLocalMap in Java](/docs/CS/Java/JDK/Concurrency/ThreadLocal.md?id=hash)



HashMap in Python



## References

1. [Hashing | Set 3 (Open Addressing)](https://www.geeksforgeeks.org/hashing-set-3-open-addressing/)
2. [Hashing | Set 2 (Separate Chaining)](https://www.geeksforgeeks.org/hashing-set-2-separate-chaining/)
