## Introduction





## BitSet

This class implements **a vector of bits that grows as needed**. Each component of the bit set has a boolean value. The bits of a BitSet are indexed by nonnegative integers. Individual indexed bits can be examined, set, or cleared. One BitSet may be used to modify the contents of another BitSet through logical AND, logical inclusive OR, and logical exclusive OR operations.
By default, all bits in the set initially have the value false.
Every bit set has a current size, which is the number of bits of space currently in use by the bit set. Note that the size is related to the implementation of a bit set, so it may change with implementation. The length of a bit set relates to logical length of a bit set and is defined independently of implementation.
Unless otherwise noted, passing a null parameter to any of the methods in a BitSet will result in a NullPointerException.
A BitSet is **not safe for multithreaded** use without external synchronization.



```java
/*
 * BitSets are packed into arrays of "words."  Currently a word is
 * a long, which consists of 64 bits, requiring 6 address bits.
 * The choice of word size is determined purely by performance concerns.
 */
private static final int ADDRESS_BITS_PER_WORD = 6;
private static final int BITS_PER_WORD = 1 << ADDRESS_BITS_PER_WORD;
private static final int BIT_INDEX_MASK = BITS_PER_WORD - 1;

// Used to shift left or right for a partial word mask
private static final long WORD_MASK = 0xffffffffffffffffL;

/**
 * @serialField bits long[]
 *
 * The bits in this BitSet.  The ith bit is stored in bits[i/64] at
 * bit position i % 64 (where bit position 0 refers to the least
 * significant bit and 63 refers to the most significant bit).
 */
@java.io.Serial
private static final ObjectStreamField[] serialPersistentFields = {
    new ObjectStreamField("bits", long[].class),
};

// The internal field corresponding to the serialField "bits".
private long[] words;

// The number of words in the logical size of this BitSet.
private transient int wordsInUse = 0;

/**
 * Whether the size of "words" is user-specified.  If so, we assume
 * the user knows what he's doing and try harder to preserve it.
 */
private transient boolean sizeIsSticky = false;
```







```java
/**
 * Creates a new bit set. All bits are initially {@code false}.
 */
public BitSet() {
    initWords(BITS_PER_WORD);
    sizeIsSticky = false;
}

/**
 * Creates a bit set whose initial size is large enough to explicitly
 * represent bits with indices in the range {@code 0} through
 * {@code nbits-1}. All bits are initially {@code false}.
 *
 * @param  nbits the initial size of the bit set
 * @throws NegativeArraySizeException if the specified initial size
 *         is negative
 */
public BitSet(int nbits) {
    // nbits can't be negative; size 0 is OK
    if (nbits < 0)
        throw new NegativeArraySizeException("nbits < 0: " + nbits);

    initWords(nbits);
    sizeIsSticky = true;
}

private void initWords(int nbits) {
    words = new long[wordIndex(nbits-1) + 1];
}

/**
 * Creates a bit set using words as the internal representation.
 * The last word (if there is one) must be non-zero.
 */
private BitSet(long[] words) {
    this.words = words;
    this.wordsInUse = words.length;
    checkInvariants();
}
```



### set

```java
/**
 * Sets the bit at the specified index to {@code true}.
 *
 * @param  bitIndex a bit index
 * @throws IndexOutOfBoundsException if the specified index is negative
 * @since  1.0
 */
public void set(int bitIndex) {
    if (bitIndex < 0)
        throw new IndexOutOfBoundsException("bitIndex < 0: " + bitIndex);

    int wordIndex = wordIndex(bitIndex);
    expandTo(wordIndex);

    words[wordIndex] |= (1L << bitIndex); // Restores invariants

    checkInvariants();
}

/**
 * Sets the bit at the specified index to the specified value.
 *
 * @param  bitIndex a bit index
 * @param  value a boolean value to set
 * @throws IndexOutOfBoundsException if the specified index is negative
 * @since  1.4
 */
public void set(int bitIndex, boolean value) {
    if (value)
        set(bitIndex);
    else
        clear(bitIndex);
}

/**
 * Sets the bits from the specified {@code fromIndex} (inclusive) to the
 * specified {@code toIndex} (exclusive) to {@code true}.
 *
 * @param  fromIndex index of the first bit to be set
 * @param  toIndex index after the last bit to be set
 * @throws IndexOutOfBoundsException if {@code fromIndex} is negative,
 *         or {@code toIndex} is negative, or {@code fromIndex} is
 *         larger than {@code toIndex}
 * @since  1.4
 */
public void set(int fromIndex, int toIndex) {
    checkRange(fromIndex, toIndex);

    if (fromIndex == toIndex)
        return;

    // Increase capacity if necessary
    int startWordIndex = wordIndex(fromIndex);
    int endWordIndex   = wordIndex(toIndex - 1);
    expandTo(endWordIndex);

    long firstWordMask = WORD_MASK << fromIndex;
    long lastWordMask  = WORD_MASK >>> -toIndex;
    if (startWordIndex == endWordIndex) {
        // Case 1: One word
        words[startWordIndex] |= (firstWordMask & lastWordMask);
    } else {
        // Case 2: Multiple words
        // Handle first word
        words[startWordIndex] |= firstWordMask;

        // Handle intermediate words, if any
        for (int i = startWordIndex+1; i < endWordIndex; i++)
            words[i] = WORD_MASK;

        // Handle last word (restores invariants)
        words[endWordIndex] |= lastWordMask;
    }

    checkInvariants();
}

/**
 * Sets the bits from the specified {@code fromIndex} (inclusive) to the
 * specified {@code toIndex} (exclusive) to the specified value.
 *
 * @param  fromIndex index of the first bit to be set
 * @param  toIndex index after the last bit to be set
 * @param  value value to set the selected bits to
 * @throws IndexOutOfBoundsException if {@code fromIndex} is negative,
 *         or {@code toIndex} is negative, or {@code fromIndex} is
 *         larger than {@code toIndex}
 * @since  1.4
 */
public void set(int fromIndex, int toIndex, boolean value) {
    if (value)
        set(fromIndex, toIndex);
    else
        clear(fromIndex, toIndex);
}
```

### clear

```java
/**
 * Sets the bit specified by the index to {@code false}.
 *
 * @param  bitIndex the index of the bit to be cleared
 * @throws IndexOutOfBoundsException if the specified index is negative
 * @since  1.0
 */
public void clear(int bitIndex) {
    if (bitIndex < 0)
        throw new IndexOutOfBoundsException("bitIndex < 0: " + bitIndex);

    int wordIndex = wordIndex(bitIndex);
    if (wordIndex >= wordsInUse)
        return;

    words[wordIndex] &= ~(1L << bitIndex);

    recalculateWordsInUse();
    checkInvariants();
}

/**
 * Sets the bits from the specified {@code fromIndex} (inclusive) to the
 * specified {@code toIndex} (exclusive) to {@code false}.
 *
 * @param  fromIndex index of the first bit to be cleared
 * @param  toIndex index after the last bit to be cleared
 * @throws IndexOutOfBoundsException if {@code fromIndex} is negative,
 *         or {@code toIndex} is negative, or {@code fromIndex} is
 *         larger than {@code toIndex}
 * @since  1.4
 */
public void clear(int fromIndex, int toIndex) {
    checkRange(fromIndex, toIndex);

    if (fromIndex == toIndex)
        return;

    int startWordIndex = wordIndex(fromIndex);
    if (startWordIndex >= wordsInUse)
        return;

    int endWordIndex = wordIndex(toIndex - 1);
    if (endWordIndex >= wordsInUse) {
        toIndex = length();
        endWordIndex = wordsInUse - 1;
    }

    long firstWordMask = WORD_MASK << fromIndex;
    long lastWordMask  = WORD_MASK >>> -toIndex;
    if (startWordIndex == endWordIndex) {
        // Case 1: One word
        words[startWordIndex] &= ~(firstWordMask & lastWordMask);
    } else {
        // Case 2: Multiple words
        // Handle first word
        words[startWordIndex] &= ~firstWordMask;

        // Handle intermediate words, if any
        for (int i = startWordIndex+1; i < endWordIndex; i++)
            words[i] = 0;

        // Handle last word
        words[endWordIndex] &= ~lastWordMask;
    }

    recalculateWordsInUse();
    checkInvariants();
}

/**
 * Sets all of the bits in this BitSet to {@code false}.
 *
 * @since 1.4
 */
public void clear() {
    while (wordsInUse > 0)
        words[--wordsInUse] = 0;
}
```





```java
/**
 * Every public method must preserve these invariants.
 */
private void checkInvariants() {
    assert(wordsInUse == 0 || words[wordsInUse - 1] != 0);
    assert(wordsInUse >= 0 && wordsInUse <= words.length);
    assert(wordsInUse == words.length || words[wordsInUse] == 0);
}

/**
 * Sets the field wordsInUse to the logical size in words of the bit set.
 * WARNING:This method assumes that the number of words actually in use is
 * less than or equal to the current value of wordsInUse!
 */
private void recalculateWordsInUse() {
    // Traverse the bitset until a used word is found
    int i;
    for (i = wordsInUse-1; i >= 0; i--)
        if (words[i] != 0)
            break;

    wordsInUse = i+1; // The new logical size
}
```





```java
/**
 * Ensures that the BitSet can accommodate a given wordIndex,
 * temporarily violating the invariants.  The caller must
 * restore the invariants before returning to the user,
 * possibly using recalculateWordsInUse().
 * @param wordIndex the index to be accommodated.
 */
private void expandTo(int wordIndex) {
    int wordsRequired = wordIndex+1;
    if (wordsInUse < wordsRequired) {
        ensureCapacity(wordsRequired);
        wordsInUse = wordsRequired;
    }
}
```



### flip

```java
/**
 * Sets the bit at the specified index to the complement of its
 * current value.
 *
 * @param  bitIndex the index of the bit to flip
 * @throws IndexOutOfBoundsException if the specified index is negative
 * @since  1.4
 */
public void flip(int bitIndex) {
    if (bitIndex < 0)
        throw new IndexOutOfBoundsException("bitIndex < 0: " + bitIndex);

    int wordIndex = wordIndex(bitIndex);
    expandTo(wordIndex);

    words[wordIndex] ^= (1L << bitIndex);

    recalculateWordsInUse();
    checkInvariants();
}

/**
 * Sets each bit from the specified {@code fromIndex} (inclusive) to the
 * specified {@code toIndex} (exclusive) to the complement of its current
 * value.
 *
 * @param  fromIndex index of the first bit to flip
 * @param  toIndex index after the last bit to flip
 * @throws IndexOutOfBoundsException if {@code fromIndex} is negative,
 *         or {@code toIndex} is negative, or {@code fromIndex} is
 *         larger than {@code toIndex}
 * @since  1.4
 */
public void flip(int fromIndex, int toIndex) {
    checkRange(fromIndex, toIndex);

    if (fromIndex == toIndex)
        return;

    int startWordIndex = wordIndex(fromIndex);
    int endWordIndex   = wordIndex(toIndex - 1);
    expandTo(endWordIndex);

    long firstWordMask = WORD_MASK << fromIndex;
    long lastWordMask  = WORD_MASK >>> -toIndex;
    if (startWordIndex == endWordIndex) {
        // Case 1: One word
        words[startWordIndex] ^= (firstWordMask & lastWordMask);
    } else {
        // Case 2: Multiple words
        // Handle first word
        words[startWordIndex] ^= firstWordMask;

        // Handle intermediate words, if any
        for (int i = startWordIndex+1; i < endWordIndex; i++)
            words[i] ^= WORD_MASK;

        // Handle last word
        words[endWordIndex] ^= lastWordMask;
    }

    recalculateWordsInUse();
    checkInvariants();
}
```





```java
/**
 * Returns the number of bits set to {@code true} in this {@code BitSet}.
 *
 * @return the number of bits set to {@code true} in this {@code BitSet}
 * @since  1.4
 */
public int cardinality() {
    int sum = 0;
    for (int i = 0; i < wordsInUse; i++)
        sum += Long.bitCount(words[i]);
    return sum;
}
```



### logic

```java
/**
 * Performs a logical <b>AND</b> of this target bit set with the
 * argument bit set. This bit set is modified so that each bit in it
 * has the value {@code true} if and only if it both initially
 * had the value {@code true} and the corresponding bit in the
 * bit set argument also had the value {@code true}.
 *
 * @param set a bit set
 */
public void and(BitSet set) {
    if (this == set)
        return;

    while (wordsInUse > set.wordsInUse)
        words[--wordsInUse] = 0;

    // Perform logical AND on words in common
    for (int i = 0; i < wordsInUse; i++)
        words[i] &= set.words[i];

    recalculateWordsInUse();
    checkInvariants();
}

/**
 * Performs a logical <b>OR</b> of this bit set with the bit set
 * argument. This bit set is modified so that a bit in it has the
 * value {@code true} if and only if it either already had the
 * value {@code true} or the corresponding bit in the bit set
 * argument has the value {@code true}.
 *
 * @param set a bit set
 */
public void or(BitSet set) {
    if (this == set)
        return;

    int wordsInCommon = Math.min(wordsInUse, set.wordsInUse);

    if (wordsInUse < set.wordsInUse) {
        ensureCapacity(set.wordsInUse);
        wordsInUse = set.wordsInUse;
    }

    // Perform logical OR on words in common
    for (int i = 0; i < wordsInCommon; i++)
        words[i] |= set.words[i];

    // Copy any remaining words
    if (wordsInCommon < set.wordsInUse)
        System.arraycopy(set.words, wordsInCommon,
                         words, wordsInCommon,
                         wordsInUse - wordsInCommon);

    // recalculateWordsInUse() is unnecessary
    checkInvariants();
}

/**
 * Performs a logical <b>XOR</b> of this bit set with the bit set
 * argument. This bit set is modified so that a bit in it has the
 * value {@code true} if and only if one of the following
 * statements holds:
 * <ul>
 * <li>The bit initially has the value {@code true}, and the
 *     corresponding bit in the argument has the value {@code false}.
 * <li>The bit initially has the value {@code false}, and the
 *     corresponding bit in the argument has the value {@code true}.
 * </ul>
 *
 * @param  set a bit set
 */
public void xor(BitSet set) {
    int wordsInCommon = Math.min(wordsInUse, set.wordsInUse);

    if (wordsInUse < set.wordsInUse) {
        ensureCapacity(set.wordsInUse);
        wordsInUse = set.wordsInUse;
    }

    // Perform logical XOR on words in common
    for (int i = 0; i < wordsInCommon; i++)
        words[i] ^= set.words[i];

    // Copy any remaining words
    if (wordsInCommon < set.wordsInUse)
        System.arraycopy(set.words, wordsInCommon,
                         words, wordsInCommon,
                         set.wordsInUse - wordsInCommon);

    recalculateWordsInUse();
    checkInvariants();
}

/**
 * Clears all of the bits in this {@code BitSet} whose corresponding
 * bit is set in the specified {@code BitSet}.
 *
 * @param  set the {@code BitSet} with which to mask this
 *         {@code BitSet}
 * @since  1.2
 */
public void andNot(BitSet set) {
    // Perform logical (a & !b) on words in common
    for (int i = Math.min(wordsInUse, set.wordsInUse) - 1; i >= 0; i--)
        words[i] &= ~set.words[i];

    recalculateWordsInUse();
    checkInvariants();
}
```


## Links
- [Collection](/docs/CS/Java/JDK/Collection/Collection.md)