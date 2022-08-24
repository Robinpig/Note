## Bloom Filter

A Bloom filter is a data structure that may report it contains an item that it does not (a false positive), but is guaranteed to report correctly if it contains the item (“no false negatives”).

bit array and hash functions

cannot delete elements

- memory size m
- hash function number k
- entity number n


$$
k=m/n\ln2

$$

## Opposite of a Bloom Filter

The opposite of a Bloom filter is a data structure that may report a false negative, but can never report a false positive.
That is, it may claim that it has not seen an item when it has, but will never claim to have seen an item it has not.

## References

1. []()
2. [The Opposite of a Bloom Filter](https://www.somethingsimilar.com/2012/05/21/the-opposite-of-a-bloom-filter/)
