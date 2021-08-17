## Introduction



A HyperLogLog is a probabilistic data structure used in order to count unique things (technically this is referred to estimating the cardinality of a set). Usually counting unique items requires using an amount of memory proportional to the number of items you want to count, because you need to remember the elements you have already seen in the past in order to avoid counting them multiple times. However there is a set of algorithms that trade memory for precision: you end with an estimated measure with a standard error, which in the case of the Redis implementation is less than 1%. The magic of this algorithm is that you no longer need to use an amount of memory proportional to the number of items counted, and instead can use a constant amount of memory! 12k bytes in the worst case, or a lot less if your HyperLogLog (We'll just call them HLL from now) has seen very few elements.

HLLs in Redis, while technically a different data structure, are encoded as a Redis string, so you can call [GET](https://redis.io/commands/get) to serialize a HLL, and [SET](https://redis.io/commands/set) to deserialize it back to the server.

Conceptually the HLL API is like using Sets to do the same task. You would [SADD](https://redis.io/commands/sadd) every observed element into a set, and would use [SCARD](https://redis.io/commands/scard) to check the number of elements inside the set, which are unique since [SADD](https://redis.io/commands/sadd) will not re-add an existing element.

While you don't really *add items* into an HLL, because the data structure only contains a state that does not include actual elements, the API is the same:

- Every time you see a new element, you add it to the count with [PFADD](https://redis.io/commands/pfadd).

- Every time you want to retrieve the current approximation of the unique elements *added* with [PFADD](https://redis.io/commands/pfadd) so far, you use the [PFCOUNT](https://redis.io/commands/pfcount).

  ```
  > pfadd hll a b c d
  (integer) 1
  > pfcount hll
  (integer) 4
  ```

An example of use case for this data structure is counting unique queries performed by users in a search form every day.

Redis is also able to perform the union of HLLs, please check the [full documentation](https://redis.io/commands#hyperloglog) for more information.







add HyperLogLog since 2.8.9

基数统计

在输入元素的数量或者体积非常非常大时，计算基数所需的空间总是固定的，并且是很小的



12KB

只会根据输入元素来计算基数，而不会储存输入元素本身，所以HyperLogLog不能像集合那样，返回输入的各个元素



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

