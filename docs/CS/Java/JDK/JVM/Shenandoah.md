## Introduction


Young GC concurrent, partial

Old GC support Concurrent Compact


Forwarding Pointer/Indirection Pointer


Memory Protection Trap

CAS implement concurrent update

Shenandoah GC in JDK 13, Part I: Load Reference Barriers
### Heap Structure

Shenandoah is a regionalized GC

- Heap division, humongous regions, etc
  are similar to G1
- Collects garbage regions first by default
- Not generational by default, no young/old separation, even temporally
- Tracking inter-region references is not
  needed by default




## Cycle

### Overview

Three major phases:
1. Snapshot-at-the-beginning concurrent mark
2. Concurrent evacuation
3. Concurrent update references (optional)


## Concurrent Mark

### Three-Color Abstraction

Assign colors to the objects:
1. White: not yet visited
2. Gray: visited, but references are not scanned yet
3. Black: visited, and fully scanned

### Stop-The-World Mark



### Mutator Problems



### SATB

### Concurrent Cleanup

Immediate Garbage Region

### Concurrent Evacuation

Brooks Pointers

### Initial Update Reference

### Concurrent Update Reference

### Final Update Reference


### Two Pauses

Init Mark:
1. Stop the mutator to avoid races
2. Color the rootset Black ← most heavy-weight
3. Arm SATB barriers

Final Mark:

1. Stop the mutator to avoid races
2. Drain the SATB buffers
3. Finish work from SATB updates ← most heavy-weight


## References
1. [Shenandoah GC in JDK 13, Part I: Load Reference Barriers](https://rkennke.wordpress.com/2019/05/15/shenandoah-gc-in-jdk13-part-i-load-reference-barriers/)