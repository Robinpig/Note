## Introduction

In 1987, Jim Gray and Gianfranco Putzolu published their now-famous five-minute rule15 for trading off memory and I/O capacity.
Their calculation compares the cost of holding a record (or page) permanently in memory with the cost of performing disk I/O each time the record (or page) is accessed,
using appropriate fractional prices of RAM chips and disk drives.
The name of their rule refers to the break-even interval between accesses.
**If a record(or page) is accessed more often, it should be kept in memory; otherwise, it should remain on disk and be read when needed.**

## The Five-Minute Rule

> Pages referenced every five minutes should be memory resident.

The five-minute rule for randomly accessed pages.
A one-minute rule applies to pages used in two-pass sequential algorithms like sort.

## The Five-Byte Rule

> Spend 5 bytes of main memory to save 1 instruction per second.

Compared with 1987, the most fundamental change may be that CPU power should be measured not in instructions but in cache line replacements.
Trading off space and time seems like a new problem in an environment with multiple levels in the memory hierarchy.

## References

1. [The 5 Minute Rule for Trading Memory for Disc Accesses and the 5 Byte Rule for Trading Memory for CPU Time](http://notes.stephenholiday.com/Five-Minute-Rule.pdf)
2. [The Five-Minute Rule Ten Years Later, and Other Computer Storage Rules of Thumb](http://notes.stephenholiday.com/Five-Minute-Rule-10-Years-Later.pdf)
3. [The Five-Minute Rule 20 Years Later (and How Flash Memory Changes the Rules)](http://notes.stephenholiday.com/Five-Minute-Rule-20-Years-Later.pdf)
