## Introduction

The string-matching problem can be stated formally as follows.
The text is given as an array T[1 : n] of length n, and the pattern is an array P[1 : m] of length m ≤ n.
The elements of P and T are characters drawn from an alphabet ∑, which is a finite set of characters.
For example, ∑ could be the set {0, 1}, or it could be the set {a, b, …, z}.
The character arrays P and T are often called strings of characters.

As Figure 1 shows, pattern P occurs with shift s in text T (or, equivalently, that pattern P occurs beginning at position s + 1 in text T)
if 0 ≤ s ≤ n – m and $T[s + 1:s + m] = P[1:m]$, that is, if T[s + j] = P[j], for 1 ≤ j ≤ m.
If P occurs with shift s in T, then s is a valid shift, and otherwise, s is an invalid shift.
The string-matching problem is the problem of finding all valid shifts with which a given pattern P occurs in a given text T.

<div style="text-align: center;">

![Fig.1. String-matching](./img/String-Matching.png)

</div>

<p style="text-align: center;">
Figure 1 An example of the string-matching problem to find all occurrences of the pattern P = abaa in the text T = abcabaabcabac.
<br/>
The pattern occurs only once in the text, at shift s = 3, which is a valid shift.
<br/>
A vertical line connects each character of the pattern to its matching character in the text, and all matched characters are shaded blue.
</p>

Except for the naive brute-force algorithm, each string-matching algorithm in this chapter performs some preprocessing based on the pattern and then finds all valid shifts.
We call this latter phase “matching.”
Here are the preprocessing and matching times for each of the string-matching algorithms.

The total running time of each algorithm is the sum of the preprocessing and matching times:


| Algorithm          | Preprocessing time | Matching time      |
| -------------------- | -------------------- | -------------------- |
| Naive              | $0$                | $O((n – m + 1)m)$ |
| Rabin-Karp         | $O(m)$             | $O((n – m + 1)m)$ |
| Finite automaton   | $O(m$              | $∑$               |
| Knuth-Morris-Pratt | $O(m)$             | $O(n)$             |
| Suffix array1      | $O(n1gn)$          | $O(m 1g n + km)$   |

We present an interesting string-matching algorithm, due to Rabin and Karp.
Although the Θ((n – m + 1)m) worst-case running time of this algorithm is no better than that of the naive method, it works much better on average and in practice.
It also generalizes nicely to other pattern-matching problems.
Then describes a string-matching algorithm that begins by constructing a finite automaton specifically designed to search for occurrences of the given pattern P in a text.
This algorithm takes $O(m |∑|)$ preprocessing time, but only Θ(n) matching time.
We present the similar, but much cleverer, [Knuth-Morris-Pratt (or KMP) algorithm](/docs/CS/Algorithms/KMP.md?id=KMP), which has the same $O(n)$ matching time, but it reduces the preprocessing time to only $O(m)$.

A completely different approach appears which examines suffix arrays and the longest common prefix array.
You can use these arrays not only to find a pattern in a text, but also to answer other questions,
such as what is the longest repeated substring in the text and what is the longest common substring between two texts.
The algorithm to form the suffix array takes $O(n 1g n)$ time and, given the suffix array, shows how to compute the longest common prefix array in $O(n)$ time.

## The naive string-matching algorithm

The *Naive-String-Matcher* procedure finds all valid shifts using a loop that checks the condition $P[1:m] = T[s+1:s+m]$ for each of the n−m+1 possible values of s.

Naive-String-Matcher(T, P, n, m)

```
for s = 0 to n – m
    if P[1:m] == T[s + 1:s + m]
        print “Pattern occurs with shift” s
```

Figure 3 portrays the naive string-matching procedure as sliding a “template” containing the pattern over the text,
noting for which shifts all of the characters on the template equal the corresponding characters in the text.
The for loop of lines 1–3 considers each possible shift explicitly.
The test in line 2 determines whether the current shift is valid.
This test implicitly loops to check corresponding character positions until all positions match successfully or a mismatch is found.
Line 3 prints out each valid shift s.

<div style="text-align: center;">

![Fig.1. Naive string matcher](./img/Naive-String-Matcher.png)

</div>

<p style="text-align: center;">
Figure 2 
The operation of the Naive-String-Matcher procedure for the pattern P = aab and the text T = acaabc.
<br/>
Imagine the pattern P as a template that slides next to the text. (a)–(d) 
The four successive alignments tried by the naive string matcher. 
In each part, vertical lines connect corresponding regions found to match (shown in blue), and a red jagged line connects the first mismatched character found, if any. 
<br/>
The algorithm finds one occurrence of the pattern, at shift s = 2, shown in part (c).
</p>

Procedure Naive-String-Matcher takes $O((n – m + 1)m)$ time, and this bound is tight in the worst case.
For example, consider the text string an (a string of na’s) and the pattern am.
For each of the n−m+1 possible values of the shift s, the implicit loop on line 2 to compare corresponding characters must execute m times to validate the shift.
The worst-case running time is thus $O((n − m + 1)m)$, which is $Θ(n^2)$ if $m = [n/2]$.
Because it requires no preprocessing, Naive-String-Matcher’s running time equals its matching time.

Naive-String-Matcher is far from an optimal procedure for this problem.
The naive string matcher is inefficient because it entirely ignores information gained about the text for one value of s when it considers other values of s.
Such information can be quite valuable, however. For example, if P = aaab and s = 0 is valid, then none of the shifts 1, 2, or 3 are valid, since T[4] = b.
The following sections examine several ways to make effective use of this sort of information.

## The Rabin-Karp algorithm

Rabin and Karp proposed a string-matching algorithm that performs well in practice and that also generalizes to other algorithms for related problems, such as two-dimensional pattern matching.
The Rabin-Karp algorithm uses Θ(m) preprocessing time, and its worst-case running time is Θ((n−m+1)m).
Based on certain assumptions, however, its average-case running time is better.

This algorithm makes use of elementary number-theoretic notions such as the equivalence of two numbers modulo a third number.
You might want to refer to Section 31.1 for the relevant definitions.

For expository purposes, let’s assume that ∑ = {0, 1, 2, …, 9}, so that each character is a decimal digit.
(In the general case, you can assume that each character is a digit in radix-d notation, so that it has a numerical value in the range 0 to d – 1, where d = |∑|.)
You can then view a string of k consecutive characters as representing a length-k decimal number.
For example, the character string 31415 corresponds to the decimal number 31,415.
Because we interpret the input characters as both graphical symbols and digits, it will be convenient in this section to denote them as digits in standard text font.

Given a pattern P[1:m], let p denote its corresponding decimal value.
In a similar manner, given a text T[1:n], let ts denote the decimal value of the length-m substring T[s + 1:s + m], for s = 0, 1, …, n – m.
Certainly, ts = p if and only if T [s + 1:s + m] = P[1:m], and thus, s is a valid shift if and only if ts = p.
If you could compute p in Θ(m) time and all the t s values in a total of Θ(n – m + 1) time,2 then you could determine all valid shifts s in Θ(m)+Θ(n − m + 1) = Θ(n) time by comparing p with each of the ts values.
(For the moment, let’s not worry about the possibility that p and the ts values might be very large numbers.)

## BF

Brute-force substring search requires ~NM character compares to search for a pattern of length M in a text of length N, in the worst case.

## MP

## KMP

Knuth, Morris, and Pratt developed a linear-time string matching algorithm that avoids computing the transition function δ altogether.
Instead, the KMP algorithm uses an auxiliary function π, which it precomputes from the pattern in Θ(m) time and stores in an array π[1:m].
The array π allows the algorithm to compute the transition function δ efficiently (in an amortized sense) “on the fly” as needed.
Loosely speaking, for any state q = 0, 1, …, m and any character a ∈ ∑, the value π[q] contains the information needed to compute δ(q, a) but that does not depend on a.
Since the array π has only m entries, whereas δ has Θ(m |∑|) entries, the KMP algorithm saves a factor of |∑| in the preprocessing time by computing π rather than δ.
Like the procedure FINITE-AUTOMATON-MATCHER, once preprocessing has completed, the KMP algorithm uses Θ(n) matching time.

The prefix function π for a pattern encapsulates knowledge about how the pattern matches against shifts of itself.
The KMP algorithm takes advantage of this information to avoid testing useless shifts in the naive pattern-matching algorithm and to avoid precomputing the full transition function δ for a string-matching automaton.

Knuth-Morris-Pratt substring search accesses no more than M+N characters to search for a pattern of length M in a text of length N.

space complexity O(N)

```java
span
```

## BM

## BMH

## RK

## Suffix arrays

The algorithms we have seen thus far in this chapter can efficiently find all occurrences of a pattern in a text.
That is, however, all they can do.
This section presents a different approach—suffix arrays—with which you can find all occurrences of a pattern in a text, but also quite a bit more.
A suffix array won’t find all occurrences of a pattern as quickly as, say, the Knuth-Morris-Pratt algorithm, but its additional flexibility makes it well worth studying.

A suffix array is simply a compact way to represent the lexicographically sorted order of all n suffixes of a length-n text.
Given a text $T[1:n]$, let $T[i:]$ denote the suffix $T[i:n]$.
The *suffix array* $SA[1:n]$ of T is defined such that if $SA[i] = j$, then $T[j:]$ is the ith suffix of T in lexicographic order.
That is, the ith suffix of T in lexicographic order is T[SA[i]:].
Along with the suffix array, another useful array is the *longest common prefix array* $LCPOE[1:n]$.
The entry $LCP[i]$ gives the length of the longest common prefix between the ith and $(i – 1)$st suffixes in the sorted order (with $LCP[SA[1]]$ defined to be 0,
since there is no prefix lexicographically smaller than $T[SA[1]:]$).
Figure 32.11 shows the suffix array and longest common prefix array for the 7-character text ratatat.

Given the suffix array for a text, you can search for a pattern via binary search on the suffix array.
Each occurrence of a pattern in the text starts some suffix of the text, and because the suffix array is in lexicographically sorted order,
all occurrences of a pattern will appear at the start of consecutive entries of the suffix array.
For example, in Figure 32.11, the three occurrences of at in ratatat appear in entries 1 through 3 of the suffix array.
If you find the length-m pattern in the length-n suffix array via binary search (taking O(m 1g n) time because each comparison takes O(m) time),
then you can find all occurrences of the pattern in the text by searching backward and forward from that spot until you find a suffix that does not start with the pattern (or you go beyond the bounds of the suffix array).
If the pattern occurs k times, then the time to find all k occurrences is $O(m 1g n + km)$.

With the longest common prefix array, you can find a longest repeated substring, that is, the longest substring that occurs more than once in the text.
If LCP[i] contains a maximum value in the LCP array, then a longest repeated substring appears in $T[SA[i]:SA[i] + LCP[i] – 1]$.
In the example of Figure 32.11, the LCP array has one maximum value: LCP[3] = 4.
Therefore, since SA[3] = 2, the longest repeated substring is T[2:5] = atat.
Exercise 32.5-3 asks you to use the suffix array and longest common prefix array to find the longest common substrings between two texts.
Next, we’ll see how to compute the suffix array for an n-character text in $O(n1gn)$ time and, given the suffix array and the text, how to compute the longest common prefix array in $O(n)$ time.

```
COMPUTE-SUFFIX-ARRAY(T, n)
// allocate arrays substr-rank[1:n], rank[1:n], and SA[1:n]
for i = 1 to n
    substr-rank[i].left-rank = ord(T[i])
    if i < n
        substr-rank[i].right-rank = ord(T[i + 1])
    else substr-rank[i].right-rank = 0
    substr-rank[i].index = i
// sort the array substr-rank into monotonically increasing order based on the left-rank attributes, using the right-rank attributes to break ties; if still a tie, the order does not matter
l = 2
while l < n
    MAKE-RANKS(substr-rank, rank, n)
    for i = 1 to n
        substr-rank[i].left-rank = rank[i]
        if i + l ≤ n
            substr-rank[i].right-rank = rank[i + l]
        else substr-rank[i].right-rank = 0
        substr-rank[i].index = i
    // sort the array substr-rank into monotonically increasing order based on the left-rank attributes, using the rightrank attributes to break ties; if still a tie, the order does not matter
    l = 2l
for i = 1 to n
    SA[i] = substr-rank[i].index
return SA

MAKE-RANKS(substr-rank, rank, n)
r = 1
rank[substr-rank[1].index] = r
for i = 2 to n
    if substr-rank[i].left-rank ≠ substr-rank[i – 1].left-rank or substr-rank[i].right-rank ≠ substr-rank[i – 1].rightrank
        r = r + 1
    rank[substr-rank[i].index] = r
```

The COMPUTE-SUFFIX-ARRAY procedure uses objects internally to keep track of the relative ordering of the substrings according to their ranks.
When considering substrings of a given length, the procedure creates and sorts an array substr-rank[1:n] of n objects, each with the following attributes:

- left-rank contains the rank of the left part of the substring.
- right-rank contains the rank of the right part of the substring.
- index contains the index into the text T of where the substring starts.

Before delving into the details of how the procedure works, let’s look at how it operates on the input text ratatat, with n = 7.
Assuming that the ord function returns the ASCII code for a character, Figure 32.12 shows the substr-rank array after the for loop of lines 2–7 and then after the sorting step in line 8.
The left-rank and right-rank values after lines 2–7 are the ranks of length-1 substrings in positions i and i + 1, for i = 1, 2, …, n.
These initial ranks are the ASCII values of the characters.
At this point, the left-rank and right-rank values give the ranks of the left and right part of each substring of length 2.
Because the substring starting at index 7 consists of only one character, its right part is empty and so its right-rank is 0.
After the sorting step in line 8, the substr-rank array gives the relative lexicographic order of all the substrings of length 2, with starting points of these substrings in the index attribute.
For example, the lexicographically smallest length-2 substring is at, which starts at position substr-rank[1].index, which equals 2.
This substring also occurs at positions substr-rank[2].index = 4 and substr-rank[3].index = 6.

## Links

- [algorithm analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)
