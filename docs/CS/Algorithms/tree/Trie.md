## Introduction

In computer science, a trie, also known as a digital tree or prefix tree, 
is a specialized search tree data structure used to store and retrieve strings from a dictionary or set. 
Unlike a [binary search tree](/docs/CS/Algorithms/tree/Binary-Tree.md), nodes in a trie do not store their associated key. 
Instead, each node's position within the trie determines its associated key, 
with the connections between nodes defined by individual characters rather than the entire key.

Tries are particularly effective for tasks such as autocomplete, spell checking, and IP routing, 
offering advantages over hash tables due to their prefix-based organization and lack of hash collisions. 
Every child node shares a common prefix with its parent node, and the root node represents the empty string.
While basic trie implementations can be memory-intensive, 
various optimization techniques such as compression and bitwise representations have been developed to improve their efficiency. 
A notable optimization is the radix tree, which provides more efficient prefix-based storage.

While tries commonly store character strings, they can be adapted to work with any ordered sequence of elements, such as permutations of digits or shapes.
A notable variant is the bitwise trie, which uses individual bits from fixed-length binary data (such as integers or memory addresses) as keys.



Time complexity in big O notation

| Operation | 	Average  | 	Worst case |
| --- |-----------|-------------|
| Search	| O(n)	| O(n)        |
| Insert	| O(n)	| O(n)        |
| Delete	| O(n)	| O(n)        |

Space complexity

|   |	Average |	Worst case |
| --- | --- | --- |
| Space |	O(n) |	O(n) |


<div style="text-align: center;">

![](https://upload.wikimedia.org/wikipedia/commons/thumb/b/be/Trie_example.svg/500px-Trie_example.svg.png)

</div>

<p style="text-align: center;">
Fig.1. Trie
</p>

```java
public class TrieNode {
    private HashMap<Character, TrieNode> children;
    private String content;
    private boolean isWord;
  
   // ...
}
```

```java
public class Trie {
    private TrieNode root;
    //...
}
```

insert

```java
public void insert(String word) {
    TrieNode current = root;

    for (char l: word.toCharArray()) {
        current = current.getChildren().computeIfAbsent(l, c -> new TrieNode());
    }
    current.setEndOfWord(true);
}
```

find

```java
public boolean find(String word) {
    TrieNode current = root;
    for (int i = 0; i < word.length(); i++) {
        char ch = word.charAt(i);
        TrieNode node = current.getChildren().get(ch);
        if (node == null) {
            return false;
        }
        current = node;
    }
    return current.isEndOfWord();
}
```

delete

```java
public void delete(String word) {
    delete(root, word, 0);
}

private boolean delete(TrieNode current, String word, int index) {
    if (index == word.length()) {
        if (!current.isEndOfWord()) {
            return false;
        }
        current.setEndOfWord(false);
        return current.getChildren().isEmpty();
    }
    char ch = word.charAt(index);
    TrieNode node = current.getChildren().get(ch);
    if (node == null) {
        return false;
    }
    boolean shouldDeleteCurrentNode = delete(node, word, index + 1) && !node.isEndOfWord();

    if (shouldDeleteCurrentNode) {
        current.getChildren().remove(ch);
        return current.getChildren().isEmpty();
    }
    return false;
}
```

## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)

## References
