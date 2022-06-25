## Introduction

In computer science, a trie, also called digital tree or prefix tree, is a type of k-ary search tree, a tree data structure used for locating specific keys from within a set.
These keys are most often strings, with links between nodes defined not by the entire key, but by individual characters.
In order to access a key (to recover its value, change it, or remove it), the trie is traversed depth-first, following the links between nodes, which represent each character in the key.

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
