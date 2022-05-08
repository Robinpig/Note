## Introduction


## ISA

Instruction Set Architectures

Computer Instructions


RISC

CISC


## Pipelining

Instruction is executed in 5 phases:

- Instruction Fetch
- Instruction Decode
- Operand Fetch
- Execute
- Operand Store


### Speedup Ratio

If i operations are performed with this pipeline, the time taken is i+(n-1) cycles.
Without pipelining, the system would require n*i cycles.
The speedup ratio is therefore
```tex
S = \sum_{i+(n-1)}{n*i}=\sum_{1+\sum_i{n-1}}{n}cycles
```
In the limit, when i=1 the value of S is 1, and when i=,the speedup is n.

### Data Hazard 

Data dependency arises when the outcome of the current operation is dependent on the result of a previous instruction that has not yet been executed to completion.
Data hazards arise because of the need to preserve the order of the execution of instructions.

Control Hazard

Structure Hazard


### Branches

#### The Delayed Branch

#### Branch Prediction

#### Dynamic Branch Prediction





## Cache

L1

```shell
cat /sys/devices/system/cpu/cpu0/cache/index0/size 
cat /sys/devices/system/cpu/cpu0/cache/index1/size
```

L2

```shell
cat /sys/devices/system/cpu/cpu0/cache/index2/size 
```

L3
```shell
cat /sys/devices/system/cpu/cpu0/cache/index3/size 
```

Instruction Cache and Data Cache

flush cache to memory and execute code



## Links

- [Operating Systems](/docs/CS/OS/OS.md)
- [Data Structures and Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Computer Network](/docs/CS/CN/CN.md)