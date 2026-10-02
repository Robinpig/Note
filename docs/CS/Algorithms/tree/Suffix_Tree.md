## Introduction

A suffix tree is a [radix tree](/docs/CS/Algorithms/tree/Radix.md) (compressed trie) that stores **all suffixes** of a given string (typically terminated by a unique sentinel `$`).
It builds on the [Trie](/docs/CS/Algorithms/tree/Trie.md) idea but compresses unary paths into single edges, so a string of length n needs only O(n) nodes instead of O(n²).

For `S = banana$` the suffixes `banana$`, `anana$`, `nana$`, `ana$`, `na$`, `a$`, `$` are all represented as root-to-leaf paths,
each leaf labeled with the starting position of that suffix.

## Structure

- Edges carry substrings (or `(start, end)` offsets into the source text) rather than single characters; an internal node exists only where suffixes branch.
- Each leaf corresponds to one suffix and stores its starting index.
- Because of the sentinel, no suffix is a prefix of another, so every suffix really does end at a leaf.
- Construction can be done in linear time (Ukkonen's online algorithm; earlier Weiner / McCreight), though the constants and implementation complexity are high.

## What It Makes Fast

Once built in O(n), many string queries become sub-linear in the text length:

| Query | Naive | Suffix tree |
| --- | --- | --- |
| Exact match of pattern P | O(n·m) | O(m + occ) |
| Longest repeated substring | O(n²) | O(n) (deepest internal node) |
| Longest common substring of two strings | — | O(n₁+n₂) |
| Longest palindromic substring | — | linear with generalized tree |
| Number of occurrences / all occurrences | — | O(m + occ) |

The matching intuition: walk from the root following P's characters; if you can spell the whole pattern, every leaf in that subtree is an occurrence, and its count equals the subtree's leaf count.

## Trade-offs

- Strength: one O(n) preprocessing step answers many different pattern/string queries, making it popular in bioinformatics (genome search), repeated-substring analysis, and data-compression research.
- Weakness: high constant factor and intricate construction; per-edge substrings and suffix links are cache-unfriendly, so memory usage can be large in practice.
- Practitioners often prefer a **suffix array** (the lexicographically sorted list of suffix starts), which captures most queries with binary search / LCP arrays at a fraction of the memory, or a suffix automaton. The suffix-array based [BWT/FM-index](https://en.wikipedia.org/wiki/FM-index) powers tools like BWA/bowtie for genome read alignment.

## Links

- [Trie](/docs/CS/Algorithms/tree/Trie.md)
- [Radix Tree](/docs/CS/Algorithms/tree/Radix.md)
- [Tree](/docs/CS/Algorithms/tree/tree.md)

## References

1. [Suffix tree - Wikipedia](https://en.wikipedia.org/wiki/Suffix_tree)
2. [Ukkonen's online algorithm](https://www.cs.helsinki.fi/u/tpkarkka/opetus/2013s/seminar/ukkonen-on-line-construction.pdf)
