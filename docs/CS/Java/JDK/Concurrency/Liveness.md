
## Introduction

A liveness failure occurs when an activity gets into a state such that it is permanently unable to make forward progress.

Liveness failures are a serious problem because there is no way to recover from them short of aborting the application.
The most common form of liveness failure is lock‐ordering deadlock. 
Avoiding lock ordering deadlock starts at design time: ensure that when threads acquire multiple locks, they do so in a consistent order. 
The best way to do this is by using open calls throughout your program.

## Deadlock


A program will be free of lock‐ordering deadlocks if all threads acquire the locks they need in a fixed global order.

Open Calls

## Starvation

Poor Responsiveness

## Livelock
