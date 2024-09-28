## Introduction

## pages

man

[tldr](https://github.com/tldr-pages/tldr)

## Counter

System

- vmstat
- mpstat
- iostat
- netstat
- sar

[nmon](https://nmon.sourceforge.io/pmwiki.php) is short for **N**igel's performance **Mon**itor **for Linux** on POWER, x86, x86_64, Mainframe & now ARM (Raspberry Pi).

Process

- ps
- top/prstat
- pmap

From /proc



## Trace

System

- tcpdump use libpcap
- snoop for Solaris
- blktrace for Linux
- Iosnoop base on DTrace
- execsnoop base on DTrace
- dtruss base on DTrace
- DTrace
- SystemTap
- perf

Process

- strace for Linux
- truss for Solaris
- gdb
- mdb



## Profiling



- oprofile
- perf
- DTrace
- SystemTap
- cachegrind
- Intel VTune Amplifier XE
- Oracle Solaris Studio



## CPU

context switch

system interrupt compare with context

```shell
cat /proc/interrupts |grep timer; sleep 10;cat /proc/interrupts |grep timer
```



vmstat 

```shell
vmstat [-s] [-n] [delay [count]]
```



top

```shell
top [d delay] [n iterations] [i] [H] [C]
```

runtime config

| option | description                   |
| ------ | ----------------------------- |
| f/F    | setup screen of Process       |
| o/O    | setup screen of display order |
| A      |                               |
| I      |                               |



- l load average
- t time
- m memory



order display

- P by %cpu 
- T by cpu time
- N by PID
- A by runtime
- i ignore idle task



sar

```shell
sar [options] [delay [count]]
```



```shell
time application
```

memory

free

```shell
free [-l] [-t] [-s delay] [-c count]
```



slabtop

```shell
slabtop [--delay n -sort={a | b | c | l | v | n | o | p | s | u}]
```



cat

```shell
cat /proc/meminfo
```



strace

ltrace



ps

## Network

iputils
- ping
- arping
- rdisc

net-tools
- ifconfig
- route
- netstat


```shell
# up/down network adapter
ifconfig en0 up/down
```



iproute2
- ss
- ip
- tc


```shell
/proc/net/
```

netlink see RFC 3549


nc


## Links

