## Introduction



A HyperLogLog is a probabilistic data structure used in order to count unique things (technically this is referred to estimating the cardinality of a set). 
Usually counting unique items requires using an amount of memory proportional to the number of items you want to count, 
because you need to remember the elements you have already seen in the past in order to avoid counting them multiple times.
However there is a set of algorithms that trade memory for precision: you end with an estimated measure with a standard error, which in the case of the Redis implementation is less than 1%. 
The magic of this algorithm is that you no longer need to use an amount of memory proportional to the number of items counted, 
and instead can use a constant amount of memory! 12k bytes in the worst case, or a lot less if your HyperLogLog (We'll just call them HLL from now) has seen very few elements.

HLLs in Redis, while technically a different data structure, are encoded as a Redis string, so you can call `GET` to serialize a HLL, and `SET` to deserialize it back to the server.

Conceptually the HLL API is like using Sets to do the same task. 
You would `SADD` every observed element into a set, and would use `SCARD` to check the number of elements inside the set, which are unique since `SADD` will not re-add an existing element.

While you don't really *add items* into an HLL, because the data structure only contains a state that does not include actual elements, the API is the same:
- Every time you see a new element, you add it to the count with `PFADD`.
- Every time you want to retrieve the current approximation of the unique elements *added* with `PFADD` so far, you use the `PFCOUNT`.

```
> pfadd hll a b c d
(integer) 1
> pfcount hll
(integer) 4
```

An example of use case for this data structure is counting unique queries performed by users in a search form every day.







add HyperLogLog since 2.8.9

cardinality counting


The Redis HyperLogLog implementation is based on the following ideas:

* The use of a 64 bit hash function as proposed in [1], in order to estimate cardinalities larger than 10^9, at the cost of just 1 additional bit per register.
* The use of 16384 6-bit registers for a great level of accuracy, using a total of 12k per key.
* The use of the Redis string data type. No new type is introduced.
* No attempt is made to compress the data structure as in [1]. Also the algorithm used is the original HyperLogLog Algorithm as in [2], 
  with the only difference that a 64 bit hash function is used, so no correction is performed for values near 2^32 as in [1].

[1] Heule, Nunkesser, Hall: HyperLogLog in Practice: Algorithmic Engineering of a State of The Art Cardinality Estimation Algorithm.
[2] P. Flajolet, Éric Fusy, O. Gandouet, and F. Meunier. Hyperloglog: The analysis of a near-optimal cardinality estimation algorithm.

Redis uses two representations:

1. A "dense" representation where every entry is represented by a 6-bit integer.
2. A "sparse" representation using run length compression suitable for representing HyperLogLogs with many registers set to 0 in a memory efficient way.



结构体如下
```c
struct hllhdr {
    char magic[4];      /* "HYLL" */
    uint8_t encoding;   /* HLL_DENSE or HLL_SPARSE. */
    uint8_t notused[3]; /* Reserved for future use, must be zero. */
    uint8_t card[8];    /* Cached cardinality, little endian. */
    uint8_t registers[]; /* Data bytes. */
};
```


Both the dense and sparse representation have a 16 byte header as follows:

```
+------+---+-----+----------+
| HYLL | E | N/U | Cardin.  |
+------+---+-----+----------+
```
The first 4 bytes are a magic string set to the bytes "HYLL"."E" is one byte encoding, currently set to HLL_DENSE or HLL_SPARSE. N/U are three not used bytes.

The "Cardin." field is a 64 bit integer stored in little endian format with the latest cardinality computed that can be reused if the data structure was not modified since the last computation
(this is useful because there are high probabilities that HLLADD operations don't modify the actual data structure and hence the approximated cardinality).

When the most significant bit in the most significant byte of the cached cardinality is set,
it means that the data structure was modified and we can't reuse the cached value that must be recomputed.




```redis
exists loglog
0
```



```
pfadd loglog
1
pfadd loglog
0
```



```
pfcount loglog
```



```
pfmerge newlog loglog
```



begin with HYLL



## Links

- [Redis Struct](/docs/CS/DB/Redis/struct/struct.md)

## References
1. [HyperLogLog: the analysis of a near-optimal cardinality estimation algorithm](http://algo.inria.fr/flajolet/Publications/FlFuGaMe07.pdf)
2. [New cardinality estimation algorithms for HyperLogLog sketches](https://arxiv.org/pdf/1702.01284.pdf)