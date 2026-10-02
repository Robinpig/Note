
Reduction in Strength 

Replace costly operation with simpler one

Shift, add instead of multiply or divide
- Utility machine dependent
- Depends on cost of multiply or divide instruction
  - On Intel Nehalem, integer multiply requires 3 CPU cycles

Recognize sequence of products


Share Commmon Subexpressions


Getting High Performance

- Good compiler and flags
- Don't do anything stupid
  - Watch out for hidden algorithmic inefficiencies
  - Write compiler-friendly code  
    - Watch out for optimization blockers: procedure calls & memory references
  - Look carefully at innermost loops(where most work is done)  
- Tune code for machine
  - Exploit instruction-level parallelism
  - Avoid unpredictable branches
  - Make code cache friendly

## Links

- [Introduction](/docs/CS/SE/APM.md)
- [Introduction](/docs/CS/SE/Architecture.md)
- [Computer Composition Principle](/docs/CS/SE/Basic.md)
- [Introduction](/docs/CS/SE/Bug.md)
- [Introduction](/docs/CS/SE/Cache.md)
- [Introduction](/docs/CS/SE/Caffeine.md)
