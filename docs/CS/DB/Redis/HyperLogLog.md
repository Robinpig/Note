## Introduction



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

