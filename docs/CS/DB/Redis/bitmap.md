## Introduction


Bitmaps are not an actual data type, but a set of bit-oriented operations defined on the [String type](/docs/CS/DB/Redis/struct/SDS.md). Since strings are binary safe blobs and their maximum length is 512 MB, they are suitable to set up to 2^32 different bits.

One of the biggest advantages of bitmaps is that they often provide extreme space savings when storing information. For example in a system where different users are represented by incremental user IDs, it is possible to remember a single bit information (for example, knowing whether a user wants to receive a newsletter) of 4 billion of users using just 512 MB of memory.



Bitmaps are trivial to split into multiple keys, for example for the sake of sharding the data set and because in general it is better to avoid working with huge keys. To split a bitmap across different keys instead of setting all the bits into a key, a trivial strategy is just to store M bits per key and obtain the key name with `bit-number/M` and the Nth bit to address inside the key with `bit-number MOD M`.

## Commands

See help by 

```shell
help @string
```





```shell
SETBIT key offset value
```



## Links

- [Redis Struct](/docs/CS/DB/Redis/struct/struct.md?id=hashes)






