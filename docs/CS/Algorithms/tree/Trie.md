## Introduction

在计算机科学中，字典树（trie），也称为数字树或前缀树，
是一种专门的搜索树数据结构，用于存储和检索字典或集合中的字符串。
与[二叉搜索树](/docs/CS/Algorithms/tree/Binary-Tree.md)不同，字典树中的节点不存储其关联的键。
相反，每个节点在字典树中的位置决定了其关联的键，
节点之间的连接由单个字符而不是整个键来定义。

字典树对于自动补全、拼写检查和 IP 路由等任务特别有效，
由于其基于前缀的组织方式和没有哈希冲突，相比哈希表具有优势。
每个子节点与其父节点共享一个公共前缀，根节点表示空字符串。
虽然基本的字典树实现可能占用大量内存，
但已经开发了各种优化技术，如压缩和位表示，以提高其效率。
一个值得注意的优化是[基数树](/docs/CS/Algorithms/tree/Radix.md)，它提供了更高效的基于前缀的存储。

虽然字典树通常存储字符串，但它们可以适用于任何有序元素序列，如数字或形状的排列。
一个值得注意的变体是位字典树，它使用来自固定长度二进制数据（如整数或内存地址）的单个位作为键。

大 O 表示法的时间复杂度

| Operation | 	Average  | 	Worst case |
| --- |-----------|-------------|
| Search	| O(n)	| O(n)        |
| Insert	| O(n)	| O(n)        |
| Delete	| O(n)	| O(n)        |

空间复杂度

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

包含少量长字符串的字典树性能比 BST 差
许多节点只有一个子节点！
长链的节点没有任何分支
基数树是字典树的一种改进，仅在需要分支时才引入节点

## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)

## References
