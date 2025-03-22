## Introduction

What is Unix?

A generous definition: Those operating systems derived from or inspired by the Research Unix systems of the 1970s.
Includes commercial Unix systems, Research Unix, NetBSD, OpenBSD, [Linux](/docs/CS/OS/Linux/Linux.md), even Plan 9 and others.

> [!Note]
>
> Those who do not understand Unix are condemned to reinvent it, poorly.    --Henny Spencer

Today, Unix runs everywhere (except a few PCs).

What makes Unix Unix ?
Something like the combination of:

- high-level programming language
- hierarchical file system
- uniform, unformatted files (text)
- separable shell
- distinct tools
- pipes
- regular expressions
- portability
- security

Not all these ideas originate in Unix, but their combination does.

> [!TIP]
>
> Keep It Simple, Stupid!

To get to 2001, you need to add networking and graphics, but those are not definitive of Unix.
Quite the opposite: these were added later and badly, with models taken largely from other systems.

The Good things about Unix are also its Bad things. The things that made it successful also limited its success.
Its strengths are also its weaknesses.

- C
- Tools
- Text files
- Portability
- Open source

The irony is Ugly.
A simple example: flat text files.

One of Unix’s greatest contributions; unused outside.
Almost no visibility beyond the Unix community!

Once, the commonest Unix program was grep. Today, it’s emacs or mozilla.
**People prefer integrated environments and browsers.**

The tyranny of forced interaction:

- No ability to step beyond the model.
- No programmability. (E.g.: Fetching maps, NYT)
- Wasting human time.
  The irony:
- Most web pages are synthesized dynamically by Unix tools.
- But the result hides that completely from the user.

The weird solution: programs that interpret HTML to drive web interactions automatically.

- Simple examples: stock, weather.
- Text-only browsing.

Flat text files are easy to use (Good) but don’t scale well (Bad).

Unix did portability first and, still, best: (Good)

- Sources in high-level language
- Operating system runs independent of hardware
- Interfaces don’t change (much) between platforms.

Unintended consequences: (Bad)

- Machine became irrelevant
- Therefore cost was only factor
- Therefore hardware got lousy, widely variable
- Therefore software had to cope, became non-portable.

The success of PCs is in large part due to the fact that, by making all hardware equivalent, good software enabled bad hardware.


1. What is the best thing about Unix?
   A: The community.
2. What is the worst thing about Unix?
   A: That there are so many communities.





1973: 信号、管道、grep
1983； BSD socket









## Links

- [Operating Systems](/docs/CS/OS/OS.md)



## References

1. [The Good, the Bad, and the Ugly: The Unix Legacy](http://herpolhode.com/rob/ugly.pdf)

