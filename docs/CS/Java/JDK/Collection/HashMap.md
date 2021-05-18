# HashMap

## HashMap



| 版本变更 | 1.7 | 1.8 |
| :---: | :---: | :---: |
| hash算法 | 扰动4次 | 更简化 |
| 存储变化 | 无 | 转变红黑树 |
| 插入链表位置 | 头部 | 尾部 |
| resize | 存在死锁 | 无死锁 |
### 简述

继承AbstractMap，实现Map接口

链表长度大于阈值（默认为 8）时，将链表转化为红黑树（将链表转换成红黑树前会判断，

如果当前数组的长度小于 64，那么会选择先进行数组扩容，而不是转换为红黑树），以减少搜索时间

### Fields

```java
//The default initial capacity - MUST be a power of two.
static final int DEFAULT_INITIAL_CAPACITY = 1 << 4; // aka 16

//The maximum capacity
static final int MAXIMUM_CAPACITY = 1 << 30;

// The load factor used when none specified in constructor.
static final float DEFAULT_LOAD_FACTOR = 0.75f;

// treeify when already has Nodes >= TREEIFY_THRESHOLD
static final int TREEIFY_THRESHOLD = 8;

//untreeify when already has Nodes =< UNTREEIFY_THRESHOLD
static final int UNTREEIFY_THRESHOLD = 6;

//The smallest table capacity for which bins may be treeified.
static final int MIN_TREEIFY_CAPACITY = 64;

//initialized on first use, and resized as necessary. length always a power of two
//also tolerate length zero in some operations
transient Node<K,V>[] table;

//Holds cached entrySet(). Note that AbstractMap fields are used for keySet() and values().
transient Set<Map.Entry<K,V>> entrySet;

//The number of key-value mappings contained in this map.
transient int size;

/**
 * The number of times this HashMap has been structurally modified
 * Structural modifications are those that change the number of mappings in
 * the HashMap or otherwise modify its internal structure (e.g.,
 * rehash).  This field is used to make iterators on Collection-views of
 * the HashMap fail-fast.  (See ConcurrentModificationException).
 */
transient int modCount;

//The next size value at which to resize (capacity * load factor).
int threshold;

final float loadFactor;
```

**loadFactor**

控制数组存放数据的疏密程度，loadFactor越趋近于1，那么 数组中存放的数据(entry)也就越多，也就越密，也就是会让链表的长度增加
loadFactor太大导致查找元素效率低，太小导致数组的利用率低，存放的数据会很分散。loadFactor的默认值为0.75f是官方给出的一个比较好的临界值



### Inner Class

#### Node

A class implements Map.Entry<K,V> and override hashCode and equals methods.

```java
static class Node<K,V> implements Map.Entry<K,V> {
    final int hash;
    final K key;
    V value;
    Node<K,V> next;

    Node(int hash, K key, V value, Node<K,V> next) {...}

    public final K getKey()        { return key; }
    public final V getValue()      { return value; }
    public final String toString() { return key + "=" + value; }

    public final int hashCode() { return Objects.hashCode(key) ^ Objects.hashCode(value);}
		
  	//set newValue and return oldValue 
    public final V setValue(V newValue) {...}
		
  	//compare address || key && value equals when instanceof Map.Entry
    public final boolean equals(Object o) {...}
}
```





#### TreeNode



```java
/**
 * Entry for Tree bins. Extends LinkedHashMap.Entry (which in turn
 * extends Node) so can be used as extension of either regular or
 * linked node.
 */
static final class TreeNode<K,V> extends LinkedHashMap.Entry<K,V> {
    TreeNode<K,V> parent;  // red-black tree links
    TreeNode<K,V> left;
    TreeNode<K,V> right;
    TreeNode<K,V> prev;    // needed to unlink next upon deletion
    boolean red;
    TreeNode(int hash, K key, V val, Node<K,V> next) {
        super(hash, key, val, next);
    }
}

//LinkedHashMap.Entry
static class Entry<K,V> extends HashMap.Node<K,V> {
    Entry<K,V> before, after;
    Entry(int hash, K key, V value, Node<K,V> next) {
        super(hash, key, value, next);
    }
}
```





### Method



#### 构造方法

HashMap 中有四个构造方法，它们分别如下：

```java
// default constructor not init table[]
public HashMap() {
    this.loadFactor = DEFAULT_LOAD_FACTOR;
 }
 
 public HashMap(Map<? extends K, ? extends V> m) {
     this.loadFactor = DEFAULT_LOAD_FACTOR;
     putMapEntries(m, false);
 }
 
 public HashMap(int initialCapacity, float loadFactor) {
     if (initialCapacity < 0)
         throw new IllegalArgumentException("Illegal initial capacity: " + initialCapacity);
     if (initialCapacity > MAXIMUM_CAPACITY)
         initialCapacity = MAXIMUM_CAPACITY;
     if (loadFactor <= 0 || Float.isNaN(loadFactor))
         throw new IllegalArgumentException("Illegal load factor: " + loadFactor);
     this.loadFactor = loadFactor;
     this.threshold = tableSizeFor(initialCapacity);
 }
```



**putMapEntries**

```java
final void putMapEntries(Map<? extends K, ? extends V> m, boolean evict) {
    int s = m.size();
    if (s > 0) {
        // 判断table是否已经初始化
        if (table == null) { // pre-size
            // 未初始化，s为m的实际元素个数
            float ft = ((float)s / loadFactor) + 1.0F;
            int t = ((ft < (float)MAXIMUM_CAPACITY) ?
                    (int)ft : MAXIMUM_CAPACITY);
            // 计算得到的t大于阈值，则初始化阈值
            if (t > threshold)
                threshold = tableSizeFor(t);
        }
        // 已初始化，并且m元素个数大于阈值，进行扩容处理
        else if (s > threshold)
            resize();
        // 将m中的所有元素添加至HashMap中
        for (Map.Entry<? extends K, ? extends V> e : m.entrySet()) {
            K key = e.getKey();
            V value = e.getValue();
            putVal(hash(key), key, value, false, evict);
        }
    }
}
```
#### put方法




```java
 public V put(K key, V value) {
   	//1. hash(key)
     return putVal(hash(key), key, value, false, true); 
 }  
                                                                
  final V putVal(int hash, K key, V value, boolean onlyIfAbsent,
                   boolean evict) {
    Node<K,V>[] tab; Node<K,V> p; int n, i;
    // 2. table未初始化或者长度为0，resize
    if ((tab = table) == null || (n = tab.length) == 0)
        n = (tab = resize()).length;
    //3. get index i= (n - 1) & hash，table[i] == null, set newNode
    if ((p = tab[i = (n - 1) & hash]) == null)
        tab[i] = newNode(hash, key, value, null);
    else {// tab[i] != null
        Node<K,V> e; K k;
        //4. compare key of tab[i], if equals then replace
        if (p.hash == hash &&
            ((k = p.key) == key || (key != null && key.equals(k))))
                e = p;
        else if (p instanceof TreeNode)
            // 5. if instanceof TreeNode, putTreeVal
            e = ((TreeNode<K,V>)p).putTreeVal(this, tab, hash, key, value);
        else {
            for (int binCount = 0; ; ++binCount) {
                if ((e = p.next) == null) {
                    // 7. not exist same key, insert at tail
                    p.next = newNode(hash, key, value, null);
                    // 8. if current nodes > 8, treeifyBin
                    if (binCount >= TREEIFY_THRESHOLD - 1) 
                        treeifyBin(tab, hash);
                    break;
                }
                // 6. if exist same key, replace
                if (e.hash == hash &&
                    ((k = e.key) == key || (key != null && key.equals(k))))
                    break;
                p = e;
            }
        }
        
        if (e != null) { 
            V oldValue = e.value;
            // 9. check onlyIfAbsent to set value 
            if (!onlyIfAbsent || oldValue == null)
                e.value = value;
            // 10. afterNodeAccess
            afterNodeAccess(e);
            return oldValue;
        }
    }
    ++modCount;// 结构性修改
    // 11. ++size > threshold, resize
    if (++size > threshold)
        resize();
    // 12. afterNodeInsertion, for LinkedHashMap to override
    afterNodeInsertion(evict);
    return null;
}
```



![put](../images/HashMap-put.png)

#### hash()

HashMap 通过 key 的 hashCode 经过扰动函数处理过后得到 hash 值，然后通过 (n - 1) & hash 判断当前元素存放的位置（这里的 n 指的是数组的长度），

如果当前位置存在元素的话，就判断该元素与要存入的元素的 hash 值以及 key 是否相同，如果相同的话，直接覆盖，不相同就通过拉链法解决冲突
JDK 1.7 的 hash 方法的性能会稍差一点点，因为毕竟扰动了 4 次

```java
static final int hash(Object key) {
  int h;
  // key.hashCode()：返回散列值也就是hashcode
  // ^ ：按位异或
  // >>>:无符号右移，忽略符号位，空位都以0补齐
  return (key == null) ? 0 : (h = key.hashCode()) ^ (h >>> 16);
}
```

扩容:

扩容这个过程涉及到 rehash、复制数据等操作，所以非常消耗性能。

threshold = capacity * loadFactor，当Size>=threshold的时候，考虑对数组扩增了

#### resize方法

进行扩容，会伴随着一次重新hash分配，并且会遍历hash表中所有的元素，是非常耗时的。在编写程序中，要尽量避免resize。

```java
final Node<K,V>[] resize() {
    Node<K,V>[] oldTab = table;
    int oldCap = (oldTab == null) ? 0 : oldTab.length;
    int oldThr = threshold;
    int newCap, newThr = 0;
    if (oldCap > 0) {
        // 超过最大值就不再扩充了，就只好随你碰撞去吧
        if (oldCap >= MAXIMUM_CAPACITY) {
            threshold = Integer.MAX_VALUE;
            return oldTab;
        }
        // 没超过最大值，就扩充为原来的2倍
        else if ((newCap = oldCap << 1) < MAXIMUM_CAPACITY && oldCap >= DEFAULT_INITIAL_CAPACITY)
            newThr = oldThr << 1; // double threshold
    }
    else if (oldThr > 0) // initial capacity was placed in threshold
        newCap = oldThr;
    else { 
        // signifies using defaults
        newCap = DEFAULT_INITIAL_CAPACITY;
        newThr = (int)(DEFAULT_LOAD_FACTOR * DEFAULT_INITIAL_CAPACITY);
    }
    // 计算新的resize上限
    if (newThr == 0) {
        float ft = (float)newCap * loadFactor;
        newThr = (newCap < MAXIMUM_CAPACITY && ft < (float)MAXIMUM_CAPACITY ? (int)ft : Integer.MAX_VALUE);
    }
    threshold = newThr;
    @SuppressWarnings({"rawtypes","unchecked"})
        Node<K,V>[] newTab = (Node<K,V>[])new Node[newCap];
    table = newTab;
    if (oldTab != null) {
        // 把每个bucket都移动到新的buckets中
        for (int j = 0; j < oldCap; ++j) {
            Node<K,V> e;
            if ((e = oldTab[j]) != null) {
                oldTab[j] = null;
                if (e.next == null)
                    newTab[e.hash & (newCap - 1)] = e;
                else if (e instanceof TreeNode)
                    ((TreeNode<K,V>)e).split(this, newTab, j, oldCap);
                else { 
                    Node<K,V> loHead = null, loTail = null;
                    Node<K,V> hiHead = null, hiTail = null;
                    Node<K,V> next;
                    do {
                        next = e.next;
                        // 原索引
                        if ((e.hash & oldCap) == 0) {
                            if (loTail == null)
                                loHead = e;
                            else
                                loTail.next = e;
                            loTail = e;
                        }
                        // 原索引+oldCap
                        else {
                            if (hiTail == null)
                                hiHead = e;
                            else
                                hiTail.next = e;
                            hiTail = e;
                        }
                    } while ((e = next) != null);
                    // 原索引放到bucket里
                    if (loTail != null) {
                        loTail.next = null;
                        newTab[j] = loHead;
                    }
                    // 原索引+oldCap放到bucket里
                    if (hiTail != null) {
                        hiTail.next = null;
                        newTab[j + oldCap] = hiHead;
                    }
                }
            }
        }
    }
    return newTab;
}  
```

JDK1.8 vs JDK1.7 at resize

1. don't need calc hash again
2. add at tail vs add at head

#### treeifyBin

```java
/**
 * Replaces all linked nodes in bin at index for given hash unless
 * table is too small, in which case resizes instead.
 */
final void treeifyBin(Node<K,V>[] tab, int hash) {
    int n, index; Node<K,V> e;
    if (tab == null || (n = tab.length) < MIN_TREEIFY_CAPACITY)
        resize();
    else if ((e = tab[index = (n - 1) & hash]) != null) {
        TreeNode<K,V> hd = null, tl = null;
        do {
            TreeNode<K,V> p = replacementTreeNode(e, null);
            if (tl == null)
                hd = p;
            else {
                p.prev = tl;
                tl.next = p;
            }
            tl = p;
        } while ((e = e.next) != null);
        if ((tab[index] = hd) != null)
            hd.treeify(tab);
    }
}
```



#### get方法

```java
public V get(Object key) {
    Node<K,V> e;
    return (e = getNode(hash(key), key)) == null ? null : e.value;
}

final Node<K,V> getNode(int hash, Object key) {
    Node<K,V>[] tab; Node<K,V> first, e; int n; K k;
    if ((tab = table) != null && (n = tab.length) > 0 &&
        (first = tab[(n - 1) & hash]) != null) {
        // 数组元素相等
        if (first.hash == hash && // always check first node
            ((k = first.key) == key || (key != null && key.equals(k))))
            return first;
        // 桶中不止一个节点
        if ((e = first.next) != null) {
            // 在树中get
            if (first instanceof TreeNode)
                return ((TreeNode<K,V>)first).getTreeNode(hash, key);
            // 在链表中get
            do {
                if (e.hash == hash &&
                    ((k = e.key) == key || (key != null && key.equals(k))))
                    return e;
            } while ((e = e.next) != null);
        }
    }
    return null;
}
```
使用红黑树而不是AVL树或者B+树

因为AVL树比红黑树保持更加严格的平衡，是以更多旋转操作导致更慢的插入和删除为代价的树，B+树所有的节点挤在一起，当数据量不多的时候会退化成链表



### HashMap 和 Hashtable 的区别

- HashMap 允许 key 和 value 为 null，Hashtable 不允许。
- HashMap 的默认初始容量为 16，Hashtable 为 11。
- HashMap 的扩容为原来的 2 倍，Hashtable 的扩容为原来的 2 倍加 1。
- HashMap 是非线程安全的，Hashtable是线程安全的。
- HashMap 的 hash 值重新计算过，Hashtable 直接使用 hashCode。
- HashMap 去掉了 Hashtable 中的 contains 方法。
- HashMap 继承自 AbstractMap 类，Hashtable 继承自 Dictionary 类。

### 总结

1. HashMap 的底层是个 Node 数组（Node<K,V>[] table），在数组的具体索引位置，如果存在多个节点，则可能是以链表或红黑树的形式存在。
2. 增加、删除、查找键值对时，定位到哈希桶数组的位置是很关键的一步，源码中是通过下面3个操作来完成这一步：
    1. 拿到 key 的 hashCode 值；
    2. 将 hashCode 的高位参与运算，重新计算 hash 值；
    3. 将计算出来的 hash 值与 “table.length - 1” 进行 & 运算。
3. HashMap 的默认初始容量（capacity）是 16，capacity 必须为 2 的幂次方；默认负载因子（load factor）是 0.75；实际能存放的节点个数（threshold，即触发扩容的阈值）= capacity * load factor。
4. HashMap 在触发扩容后，阈值会变为原来的 2 倍，并且会对所有节点进行重 hash 分布，重 hash 分布后节点的新分布位置只可能有两个：“原索引位置” 或 “原索引+oldCap位置”。例如 capacity 为16，索引位置 5 的节点扩容后，只可能分布在新表 “索引位置5” 和 “索引位置21（5+16）”。
5. 导致 HashMap 扩容后，同一个索引位置的节点重 hash 最多分布在两个位置的根本原因是：1）table的长度始终为 2 的 n 次方；2）索引位置的计算方法为 “(table.length - 1) & hash”。HashMap 扩容是一个比较耗时的操作，定义 HashMap 时尽量给个接近的初始容量值。
6. HashMap 有 threshold 属性和 loadFactor 属性，但是没有 capacity 属性。初始化时，如果传了初始化容量值，该值是存在 threshold 变量，并且 Node 数组是在第一次 put 时才会进行初始化，初始化时会将此时的 threshold 值作为新表的 capacity 值，然后用 capacity 和 loadFactor 计算新表的真正 threshold 值。
7. 当同一个索引位置的节点在增加后达到 9 个时，并且此时数组的长度大于等于 64，则会触发链表节点（Node）转红黑树节点（TreeNode），转成红黑树节点后，其实链表的结构还存在，通过 next 属性维持。链表节点转红黑树节点的具体方法为源码中的 treeifyBin 方法。而如果数组长度小于64，则不会触发链表转红黑树，而是会进行扩容。
8. 当同一个索引位置的节点在移除后达到 6 个时，并且该索引位置的节点为红黑树节点，会触发红黑树节点转链表节点。红黑树节点转链表节点的具体方法为源码中的 untreeify 方法。
9. HashMap 在 JDK 1.8 之后不再有死循环的问题，JDK 1.8 之前存在死循环的根本原因是在扩容后同一索引位置的节点顺序会反掉。
10. HashMap 是非线程安全的，在并发场景下使用 ConcurrentHashMap 来代替。



1. HashMap 的存取是没有顺序的。
2. KV 均允许为 NULL。
3. 多线程情况下该类不安全，可以考虑用 HashTable。
4. JDk8底层是数组 + 链表 + 红黑树，JDK7底层是数组 + 链表。
5. 初始容量和装载因子是决定整个类性能的关键点，轻易不要动。
6. HashMap是**懒汉式**创建的，只有在你put数据时候才会 build。
7. 单向链表转换为红黑树的时候会先变化为**双向链表**最终转换为**红黑树**，切记双向链表跟红黑树是`共存`的。
8. 对于传入的两个`key`，会强制性的判别出个高低，目的是为了决定向左还是向右放置数据。
9. 链表转红黑树后会努力将红黑树的`root`节点和链表的头节点 跟`table[i]`节点融合成一个。
10. 在删除的时候是先判断删除节点红黑树个数是否需要转链表，不转链表就跟`RBT`类似，找个合适的节点来填充已删除的节点。
11. 红黑树的`root`节点`不一定`跟`table[i]`也就是链表的头节点是同一个，三者同步是靠`MoveRootToFront`实现的。而`HashIterator.remove()`会在调用`removeNode`的时候`movable=false`。



## ConcurrentHashMap

这是我自己阅读源码后，比HashMap的会复杂很多，画的一个流程图如下所示：

![image.png](http://notfound9.github.io/interviewGuide/static/3.png)

#### [1.判断null值](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=_1判断null值)

判断key==null 或者 value == null，如果是，抛出空指针异常。

#### [2.计算hash](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=_2计算hash)

根据key计算hash值(计算结果跟HashMap是一致的，写法不同)。

#### [3.进入for循环，插入或更新元素](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=_3进入for循环，插入或更新元素)

- ##### [3.1 如果 tab==null || tab.length==0，说明数组未初始化](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=_31-如果-tabnull-tablength0，说明数组未初始化)

  说明当前数组tab还没有初始化。

  那么调用initTable()方法初始化tab。（在initTable方法中，为了控制只有一个线程对table进行初始化，当前线程会通过**CAS操作对SIZECTL变量赋值为-1**，如果赋值成功，线程才能初始化table，否则会调用Thread.yield()方法让出时间片）。

- ##### [3.2 如果f ==null，说明当前下标没有哈希冲突的键值对](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=_32-如果f-null，说明当前下标没有哈希冲突的键值对)

  说明当前数组下标还没有哈希冲突的键值对。

  Node<K,V> f是根据key的hash值计算得到数组下标，下标存储的元素，f可能是null，也有可能是链表头节点，红黑树根节点或迁移标志节点ForwardNode）

  那么根据key和value创建一个Node，使用**CAS操作设置在当前数组下标下**，并且break出for循环。

- ##### [3.3 如果f != null && f.hash = -1，说明存储的是标志节点，表示在扩容](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=_33-如果f-null-ampamp-fhash-1，说明存储的是标志节点，表示在扩容)

  说明ConcurrentHashMap正在在扩容，当前的节点f是一个标志节点，当前下标存储的hash冲突的元素已经迁移了。

  那么当前线程会调用helpTransfer()方法来辅助扩容，扩容完成后会将tab指向新的table，然后继续执行for循环。

- ##### 3.4 除上面三种以外情况，说明是下标存储链表或者是红黑树

  说明f节点是一个链表的头结点或者是红黑树的根节点，那么对f加sychronize同步锁，然后进行以下判断：

  - f.hash > 0

    如果是f的hash值大于0，当前数组下标存储的是一个链表，f是链表的头结点。

    对链表进行遍历，如果有节点跟当前需要插入节点的hash值相同，那么对节点的value进行更新，否则根据key，value创建一个Node<K,V>，添加到链表末尾。

  - f instanceof TreeBin

    如果f是TreeBin类型，那么说明当前数组下标存储的是一个红黑树，f是红黑树的根节点，调用putTreeVal方法，插入或更新节点。

```
如果f是TreeBin类型，那么说明当前数组下标存储的是一个红黑树，f是红黑树的根节点，调用putTreeVal方法，插入或更新节点。点击复制代码复制出错复制成功
```

- 插入完成后，判断binCount（数组下标存储是一个链表时，binCount是链表长度），当binCount超过8时，**并且数组的长度大于64时**，那么调用treeifyBin方法将链表转换为红黑树。最后break出for循环。



### HashMap与HashTable，ConcurrentHashMap的区别是什么？

主要从底层数据结构，线程安全，执行效率，是否允许Null值，初始容量及扩容，hash值计算来进行分析。

#### [1.底层数据结构](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=_1底层数据结构)

```java
transient Node<K,V>[] table; //HashMap

transient volatile Node<K,V>[] table;//ConcurrentHashMap

private transient Entry<？,？>[] table;//HashTable
```

#### HashMap=数组+链表+红黑树

HashMap的底层数据结构是一个数组+链表+红黑树，数组的每个元素存储是一个链表的头结点，链表中存储了一组哈希值冲突的键值对，通过链地址法来解决哈希冲突的。为了避免链表长度过长，影响查找元素的效率，当链表的长度>8时，会将链表转换为红黑树，链表的长度<6时，将红黑树转换为链表(但是红黑树转换为链表的时机不是在删除链表时，而是在扩容时，发现红黑树分解后的两个链表<6，就按链表处理，否则就建立两个小的红黑树，设置到扩容后的位置)。之所以临界点为8是因为红黑树的查找时间复杂度为logN，链表的平均时间查找复杂度为N/2，当N为8时，logN为3，是小于N/2的，正好可以通过转换为红黑树减少查找的时间复杂度。

#### [ConcurrentHashMap=数组+链表+红黑树](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=concurrenthashmap数组链表红黑树)

ConcurrentHashMap底层数据结构跟HashMap一致，底层数据结构是一个数组+链表+红黑树。只不过使用了volatile来进行修饰它的属性，来保证内存可见性(一个线程修改了这些属性后，会使得其他线程中对于该属性的缓存失效，以便下次读取时取最新的值)。

#### [Hashtable=数组+链表](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=hashtable数组链表)

Hashtable底层数据结构跟HashMap一致，底层数据结构是一个数组+链表，也是通过链地址法来解决冲突，只是链表过长时，不会转换为红黑树来减少查找时的时间复杂度。Hashtable属于历史遗留类，实际开发中很少使用。

#### [2.线程安全](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=_2线程安全)

##### [HashMap 非线程安全](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=hashmap-非线程安全)

HashMap是非线程安全的。（例如多个线程插入多个键值对，如果两个键值对的key哈希冲突，可能会使得两个线程在操作同一个链表中的节点，导致一个键值对的value被覆盖）

##### [HashTable 线程安全](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=hashtable-线程安全)

HashTable是线程安全的，主要通过使用synchronized关键字修饰大部分方法，使得每次只能一个线程对HashTable进行同步修改，性能开销较大。

##### [ConcurrentHashMap 线程安全](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=concurrenthashmap-线程安全)

ConcurrentHashMap是线程安全的，主要是通过CAS操作+synchronized来保证线程安全的。

##### CAS操作

往ConcurrentHashMap中插入新的键值对时，如果对应的数组下标元素为null，那么通过CAS操作原子性地将节点设置到数组中。

```java
//这是添加新的键值对的方法
final V putVal(K key, V value, boolean onlyIfAbsent) {
...其他代码
  if ((f = tabAt(tab, i = (n - 1) & hash)) == null) {
    if (casTabAt(tab, i, null, new Node<K,V>(hash, key, value, null)))                 break; // 因为对应的数组下标元素为null，所以null作为预期值，new Node<K,V>(hash, key, value, null)作为即将更新的值，只有当内存中的值与即将预期值一致时，才会进行更新，保证原子性。
  }
...其他代码
}
static final <K,V> boolean casTabAt(Node<K,V>[] tab, int i,
                                        Node<K,V> c, Node<K,V> v) {
        return U.compareAndSwapObject(tab, ((long)i << ASHIFT) + ABASE, c, v);
}
```



##### synchronized

往ConcurrentHashMap中插入新的键值对时，如果对应的数组下标元素不为null，那么会对数组下标存储的元素(也就是链表的头节点)加synchronized锁， 然后进行插入操作，

```java
Node<K,V> f = tabAt(tab, i = (n - 1) & hash));
synchronized (f) {//f就是数组下标存储的元素
    if (tabAt(tab, i) == f) {
        if (fh >= 0) {//当前下标存的是链表
            binCount = 1;
            for (Node<K,V> e = f;; ++binCount) {//遍历链表
                K ek;
                if (e.hash == hash &&
                    ((ek = e.key) == key ||
                     (ek != null && key.equals(ek)))) {
                    oldVal = e.val;
                    if (!onlyIfAbsent)
                        e.val = value;
                    break;
                }
                Node<K,V> pred = e;
                if ((e = e.next) == null) {
                    pred.next = new Node<K,V>(hash, key,
                                              value, null);
                    break;
                }
            }
        }
        else if (f instanceof TreeBin) {//当前下标存的是红黑树
            Node<K,V> p;
            binCount = 2;
            if ((p = ((TreeBin<K,V>)f).putTreeVal(hash, key,
                                           value)) != null) {
                oldVal = p.val;
                if (!onlyIfAbsent)
                    p.val = value;
            }
        }
    }
}
```

#### [3.执行效率

因为HashMap是非线程安全的，执行效率会高一些，其次是ConcurrentHashMap，因为HashTable在进行修改和访问时是对整个HashTable加synchronized锁，多线程访问时，同一时间点，只有一个线程可以访问或者添加键值对，所以效率最低。

#### [4.是否允许null值出现

HashMap的key和value都可以为null，如果key为null，那么计算的hash值会是0，最终计算得到的数组下标也会是0，所以key为null的键值对会存储在数组中的首元素的链表中。value为null的键值对也能正常插入，跟普通键值对插入过程一致。

```java
static final int hash(Object key) {
    int h;
    return (key == null) ？ 0 : (h = key.hashCode()) ^ (h >>> 16);
}
```

HashTable的键和值都不能为null，如果将HashTable的一个键值对的key设置为null，因为null值没法调用hashCode()方法获取哈希值，所以会抛出空指针异常。同样value为null时，在put方法中会进行判断，然后抛出空指针异常。

```java
public synchronized V put(K key, V value) {
        // Make sure the value is not null
        if (value == null) {
            throw new NullPointerException();
        }
        Entry<？,？> tab[] = table;
        int hash = key.hashCode();
        //...
}
```

ConcurrentHashMap的键和值都不能为null,在putVal方法中会进行判断，为null会抛出空指针异常。

```java
final V putVal(K key, V value, boolean onlyIfAbsent) {
    if (key == null || value == null) throw new NullPointerException();
    int hash = spread(key.hashCode());
    //...
}
```

#### [5.初始容量及扩容](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=_5初始容量及扩

不指定初始容量](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=不指定初始容量)

如果不指定初始容量，HashMap和ConcurrentHashMap默认会是16，HashTable的容量默认会是11。

##### [指定初始容量](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=指定初始容

如果指定了初始容量，HashMap和ConcurrentHashMap的容量会是比初始容量稍微大一些的2的幂次方大小，HashTable会使用初始容量，

##### [扩容](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=扩容)

扩容时，如果远长度是N，HashMap和ConcurrentHashMap扩容时会是2N，HashTable则是2N+1。

#### [6.hash值计算](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=_6hash值计算)

HashTable会扩容为2N+1，HashTable之所以容量取11，及扩容时是是2N+1，是为了保证 HashTable的长度是一个素数，因为数组的下标是用key的hashCode与数组的长度取模进行计算得到的，而当数组的长度是素数时，可以保证计算得到的数组下标分布得更加均匀，可以看看这篇文章http://zhaox.github.io/algorithm/2015/06/29/hash

```java
public synchronized V put(K key, V value) {
         ...其他代码
        // Makes sure the key is not already in the hashtable.
        Entry<？,？> tab[] = table;
        int hash = key.hashCode();
        int index = (hash & 0x7FFFFFFF) % tab.length;
        ...其他代码
}
```

HashMap和ConcurrentHashMap的hash值都是通过将key的hashCode()高16位与低16位进行异或运算(这样可以保留高位的特征，避免一些key的hashCode高位不同，低位相同，造成hash冲突)，得到hash值，然后将hash&(n-1)计算得到数组下标。（n为数组的长度，因为当n为2的整数次幂时，hash mod n的结果在数学上等于hash&(n-1)，而计算机进行&运算更快，所以这也是HashMap的长度总是设置为2的整数次幂的原因）

```java
//HashMap计算hash值的方法
static int hash(Object key) {
    int h;
    return (key == null) ？ 0 : (h = key.hashCode()) ^ (h >>> 16); 
}
//ConcurrentHashMap计算hash值的方法 
static  int spread(int h) {//h是对象的hashCode
    return (h ^ (h >>> 16)) & HASH_BITS;// HASH_BITS = 0x7fffffff;
}
```

### [HashMap扩容后是否需要rehash？

在JDK1.8以后，不需要rehash，因为键值对的Hash值主要是根据key的hashCode()的高16位与低16位进行异或计算后得到，根据hash%length，计算得到数组的下标index，因为length是2的整数次幂，当扩容后length变为原来的两倍时，hash%(2*length)的计算结果结果差别在于第length位的值是1还是0，如果是0，那么在新数组中的index与旧数组的一直，如果是1，在新数组中的index会是旧数组中的数组中的index+length。

### [HashMap扩容是怎样扩容的，为什么都是2的N次幂的大小？

#### [触发扩容](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=触发扩容)

在没有指定初始长度的情况下，HashMap数组的默认长度为16，在添加一个新的键值对时，会调用putVal()方法，在方法中，成功添加一个新的键值对以后，会判断当前的元素个数是否超过阀值(数组长度*负载因子0.75)，如果超过那么调用resize方法进行扩容。具体的扩容步骤如下：

#### [计算扩容后的长度](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=计算扩容后的长度)

- ##### [如果当前table为null](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=如果当前table为null)

  那么直接初始化一个数组长度为16的数组返回。

- ##### [如果当前table的length已经大于HashMap指定的最大值2的30次方](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=如果当前table的length已经大于hashmap指定的最大值2的30次方)

  那么直接返回旧table，不进行扩容。

- ##### [其他情况](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=其他情况)

  将table的length扩容为2倍，然后计算新的扩容阀值（新数组长度*0.75）。

  #### [初始化新数组

会根据扩容后的数组长度初始化话一个新的数组，并且直接赋值给当前hashMap的成员变量table。

```java
Node<K,V>[] newTab = (Node<K,V>[])new Node[newCap];
table = newTab;
```

这一步就很有意思，也是HashMap是非线程安全的表现之一，因为此时newTab还是一个空数组，如果有其他线程访问HashMap，根据key去newTab中找键值对，会返回null。实际上可能key是有对应的键值对的，只不过键值对都保存在旧table中，还没有迁移过来。

（与之相反，HashTable在解决扩容时其他线程访问的问题，是通过对大部分方法使用sychronized关键字修饰，也就是某个线程在执行扩容方法时，会对HashTable对象加锁，其他线程无法访问HashTable。ConcurrentHashMap在解决扩容时其他线程访问的问题，是通过设置**ForwardingNode标识节点**来解决的，扩容时，某个线程对数组中某个下标下所有Hash冲突的元素进行迁移时，那么会将数组下标的数组元素设置为一个**标识节点ForwardingNode**，之后其他线程在访问时，如果发现key的hash值映射的数组下标对应是一个**标识节点ForwardingNode**（ForwardingNode继承于普通Node，区别字啊呀这个节点的hash值会设置为-1，并且会多一个指向扩容过程中新tab的指针nextTable），那么会根据ForwardingNode中的nextTable变量，去新的tab中查找元素。（如果是添加新的键值对时发现是ForwardingNode，当前线程会进行辅助扩容或阻塞等待，扩容完成后去新数组中更新或插入元素）

#### [迁移元素](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=迁移元素)

因为HashMap的数组长度总是2的N次幂，扩容后也是变为原来的2倍，所以有一个数学公式，当length为2的N次幂时，

```java
hash%length=hash&(length-1)
```

而因为length是2的N次幂，length-1在二进制中其实是N个1。例如：

length为16，length用2进制表示是10000，

length-1是15，用2进制表示是1111，

2*length为32，length用2进制表示是100000，

2*length-1为31，length用2进制表示是11111，

所以hash&(length-1)的计算结果与hash&(2*length-1)的计算结果差别在于扩容后需要多看一位，也就是看第N位的1与hash值的&结果。

假设原数组长度为16，length-1二进制表示为1111。key1的hash值为9，二进制表示为01001，key2的hash值为25，11001，

所以hash&(length-1)的结果只要看低4位的结果，9和25的低4位都是1001，所以计算结果一致，计算结果都是9，所以在数组中处于数组下标为9的元素链表中。

扩容后数组长度为32，length-1二进制表示为11111，key1的hash值为9，二进制表示为01001，key2的hash值为25，11001，

所以hash&(2*length-1)的结果需要看低5位的结果，9和25的低4位都是1001，所以计算结果不一致，计算结果都是9和25，因为key2的hash值的第五位为1，key1的hash值的第五位为0，所以会多16，也就是原数组长度的大小。

所以原数组同一下标index下的链表存储的hash冲突的元素，扩容后在新数组中的下标newIndex要么为index，要么为index+length（去决定于hash值的第N位为1，还是0，也就是hash&length的结果，原数组长度length为2的N-1次幂）

所以会遍历链表(或者红黑树)，然后对数组下标index下每个节点计算hash&length的结果，然后存放在两个不同的临时链表中，遍历完成后，hash&length结果为0的元素组成的临时链表会存储在新数组index位置，hash&length结果为1的元素组成的临时链表会存储在新数组index+length位置。

#### ConcurrentHashMap是怎么记录元素个数size的？

HashMap默认是非线程安全的，可以认为每次只有一个线程来执行操作，所以hashMap就使用一个很简单的int类型的size变量来记录HashMap键值对数量就行了。

HashMap记录键值对数量的实现如下：

```java
transient int size;
public int size() {
    return size;
}
```

ConcurrentHashMap记录键值对数量的实现如下：

```java
//size方法最大只能返回Integer.MAX_VALUE
public int size() {
    long n = sumCount();
    return ((n < 0L) ？ 0 : (n > (long)Integer.MAX_VALUE) ？Integer.MAX_VALUE : (int)n);
}

//mappingCount方法可以返回long类型的最大值，
public long mappingCount() {
    long n = sumCount();
    return (n < 0L) ？ 0L : n; // ignore transient negative values
}

private transient volatile long baseCount;
private transient volatile CounterCell[] counterCells;

//sumCount会返回sumCount加上CounterCells数组中每个元素as存储的value
final long sumCount() {
        CounterCell[] as = counterCells; CounterCell a;
        long sum = baseCount;
        if (as != null) {
                for (int i = 0; i < as.length; ++i) {
                    if ((a = as[i]) != null)
                            sum += a.value;
                }
        }
        return sum;
}

@sun.misc.Contended //这个注解可以避免伪共享，提升性能。加与不加，性能差距达到了 5 倍。在缓存系统中，由于一个缓存行是出于32-256个字节之间，常见的缓存行为64个字节。而一般的变量可能达不到那么多字节，所以会出现多个相互独立的变量存储在一个缓存行中的情况，此时即便多线程访问缓存行上相互独立变量时，也涉及到并发竞争，会有性能开销，加了@sun.misc.Contended这个注解，在jDK8中，会对对象前后都增加128字节的padding，使用2倍于大多数硬件缓存行的大小来避免相邻扇区预取导致的伪共享冲突。
static final class CounterCell {
    volatile long value;
    CounterCell(long x) { value = x; }
}
```

每次添加x个新的键值对后，会调用addCount()方法使用CAS操作对baseCount+x，如果操作失败，那么会新建一个CounterCell类型的对象，保存新增的数量x，并且将对象添加到CounterCells数组中去。 

### 为什么ConcurrentHashMap，HashTable不支持key，value为null？

因为HashMap是非线程安全的，默认单线程环境中使用，如果get(key)为null，可以通过containsKey(key) 方法来判断这个key的value为null，还是不存在这个key，而ConcurrentHashMap，HashTable是线程安全的， 在多线程操作时，因为get(key)和containsKey(key)两个操作和在一起不是一个原子性操作，可能在containsKey(key)时发现存在这个键值对，但是get(key)时，有其他线程删除了键值对，导致get(key)返回的Node是null，然后执行方法时抛出异常。所以无法区分value为null还是不存在key。 至于ConcurrentHashMap，HashTable的key不能为null，主要是设计者的设计意图。

### HashSet和HashMap的区别？

HashMap主要是用于存储非重复键值对，HashSet存储非重复的对象。虽然HashMap是继承于AbstractMap，实现了Map接口，HashSet继承于AbstractSet，实现了Set接口。但是由于它们都有去重的需求，所以HashSet主要实现都是基于HashMap的（如果需要复用一个类，我们可以使用继承模式，也可以使用组合模式。组合模式就是将一个类作为新类的组成部分，以此来达到复用的目的。）例如，在HashSet类中，有一个HashMap类型的成员变量map，这就是组合模式的应用。

```java
    public class HashSet<E>
    extends AbstractSet<E>
    implements Set<E>, Cloneable, java.io.Serializable
{
    private transient HashMap<E,Object> map;
    private static final Object PRESENT = new Object();//占位对象
    public HashSet() {
        map = new HashMap<>();
    }
    public boolean add(E e) {
        return map.put(e, PRESENT)==null;//占位对象
    }
}点击复制代码复制出错复制成功
```

在HashSet的构造方法中，创建了一个HashMap，赋值给map属性，之后在添加元素时，就是将元素作为key添加到HashMap中，只不过value是一个占位对象PRESENT。除了 `clone()`、`writeObject()`、`readObject()`是 HashSet 自己不得不实现之外，其他方法都是直接调用 HashMap 中的方法。那么HashMap又是如何实现key不重复的呢？

在调用HashMap的putVal方法添加新的键值对时，会进行如下操作：

1.根据key计算hash值。

2.根据hash值映射数组下标，然后获取数组下标的对应的元素。

3.数组下标存储的是一个链表，链表包含了哈希冲突的元素，会对链表进行遍历，判断hash1==hash2，除此以外，还必须要key1==key2，或者key1.equals(key2)。

因为两个不同的对象的hashCode可能相等，但是相同的对象的hashCode肯定相等，

==是判断两个变量或实例是不是指向同一个内存地址，如果是同一个内存地址，对象肯定相等。

```
int hash = hash(key);//根据key计算hash值
p = tab[i = (n - 1) & hash];//根据hash值映射数组下标，然后获取数组下标的对应的元素。
for (int binCount = 0; ; ++binCount) {//数组下标存储的是一个链表，链表包含了哈希冲突的元素，会对链表进行遍历，判断每个节点的hash值与插入元素的hash值是否相等，并且是存储key对象的地址相等，或者key相等。
if (e.hash == hash &&
    ((k = e.key) == key || (key != null && key.equals(k))))
        break;
        p = e;
}点击复制代码复制出错复制成功
```

### [HashMap遍历时删除元素的有哪些实现方法？](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=hashmap遍历时删除元素的有哪些实现方法？)

首先结论如下：

第1种方法 - for-each遍历HashMap.entrySet，使用HashMap.remove()删除(结果：抛出异常)。

第2种方法-for-each遍历HashMap.keySet，使用HashMap.remove()删除(结果：抛出异常)。

第3种方法-使用HashMap.entrySet().iterator()遍历删除(结果：正确删除)。

下面让我们来详细探究一下原因吧！

HashMap的遍历删除方法与ArrayList的大同小异，只是api的调用方式不同。首先初始化一个HashMap，我们要删除key包含"3"字符串的键值对。

```java
HashMap<String,Integer> hashMap = new HashMap<String,Integer>();
hashMap.put("key1",1);
hashMap.put("key2",2);
hashMap.put("key3",3);
hashMap.put("key4",4);
hashMap.put("key5",5);
hashMap.put("key6",6);点击复制代码复制出错复制成功
```

### [第1种方法 - for-each遍历HashMap.entrySet，使用HashMap.remove()删除(结果：抛出异常)](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=第1种方法-for-each遍历hashmapentryset，使用hashmapremove删除结果：抛出异常)

```java
for (Map.Entry<String,Integer> entry: hashMap.entrySet()) {
        String key = entry.getKey();
        if(key.contains("3")){
            hashMap.remove(entry.getKey());
        }
     System.out.println("当前HashMap是"+hashMap+" 当前entry是"+entry);

}点击复制代码复制出错复制成功
```

输出结果：

```java
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key3=3, key4=4} 当前entry是key1=1
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key3=3, key4=4} 当前entry是key2=2
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key3=3, key4=4} 当前entry是key5=5
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key3=3, key4=4} 当前entry是key6=6
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key4=4} 当前entry是key3=3
Exception in thread "main" java.util.ConcurrentModificationException
    at java.util.HashMap$HashIterator.nextNode(HashMap.java:1429)
    at java.util.HashMap$EntryIterator.next(HashMap.java:1463)
    at java.util.HashMap$EntryIterator.next(HashMap.java:1461)
    at com.test.HashMapTest.removeWayOne(HashMapTest.java:29)
    at com.test.HashMapTest.main(HashMapTest.java:22)点击复制代码复制出错复制成功
```

### [第2种方法-for-each遍历HashMap.keySet，使用HashMap.remove()删除(结果：抛出异常)](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=第2种方法-for-each遍历hashmapkeyset，使用hashmapremove删除结果：抛出异常)

```java
Set<String> keySet = hashMap.keySet();
for(String key : keySet){
    if(key.contains("3")){
        keySet.remove(key);
    }
    System.out.println("当前HashMap是"+hashMap+" 当前key是"+key);
}点击复制代码复制出错复制成功
```

输出结果如下：

```java
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key3=3, key4=4} 当前key是key1
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key3=3, key4=4} 当前key是key2
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key3=3, key4=4} 当前key是key5
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key3=3, key4=4} 当前key是key6
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key4=4} 当前key是key3
Exception in thread "main" java.util.ConcurrentModificationException
    at java.util.HashMap$HashIterator.nextNode(HashMap.java:1429)
    at java.util.HashMap$KeyIterator.next(HashMap.java:1453)
    at com.test.HashMapTest.removeWayTwo(HashMapTest.java:40)
    at com.test.HashMapTest.main(HashMapTest.java:23)点击复制代码复制出错复制成功
```

### [第3种方法-使用HashMap.entrySet().iterator()遍历删除(结果：正确删除)](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=第3种方法-使用hashmapentrysetiterator遍历删除结果：正确删除)

```java
Iterator<Map.Entry<String, Integer>> iterator  = hashMap.entrySet().iterator();
while (iterator.hasNext()) {
    Map.Entry<String, Integer> entry = iterator.next();
    if(entry.getKey().contains("3")){
        iterator.remove();
    }
    System.out.println("当前HashMap是"+hashMap+" 当前entry是"+entry);
}点击复制代码复制出错复制成功
```

输出结果：

```java
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key4=4, deletekey=3} 当前entry是key1=1
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key4=4, deletekey=3} 当前entry是key2=2
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key4=4, deletekey=3} 当前entry是key5=5
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key4=4, deletekey=3} 当前entry是key6=6
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key4=4, deletekey=3} 当前entry是key4=4
当前HashMap是{key1=1, key2=2, key5=5, key6=6, key4=4} 当前entry是deletekey=3点击复制代码复制出错复制成功
```

第1种方法和第2种方法抛出ConcurrentModificationException异常与上面ArrayList错误遍历-删除方法的原因一致，HashIterator也有一个expectedModCount，在遍历时获取下一个元素时，会调用next()方法，然后对 expectedModCount和modCount进行判断，不一致就抛出ConcurrentModificationException异常。

```java
abstract class HashIterator {
    Node<K,V> next;        // next entry to return
    Node<K,V> current;     // current entry
    int expectedModCount;  // for fast-fail
    int index;             // current slot

    HashIterator() {
        expectedModCount = modCount;
        Node<K,V>[] t = table;
        current = next = null;
        index = 0;
        if (t != null && size > 0) { // advance to first entry
            do {} while (index < t.length && (next = t[index++]) == null);
        }
    }

    public final boolean hasNext() {
        return next != null;
    }

    final Node<K,V> nextNode() {
        Node<K,V>[] t;
        Node<K,V> e = next;
        if (modCount != expectedModCount)
            throw new ConcurrentModificationException();
        if (e == null)
            throw new NoSuchElementException();
        if ((next = (current = e).next) == null && (t = table) != null) {
            do {} while (index < t.length && (next = t[index++]) == null);
        }
        return e;
    }

    public final void remove() {
        Node<K,V> p = current;
        if (p == null)
            throw new IllegalStateException();
        if (modCount != expectedModCount)
            throw new ConcurrentModificationException();
        current = null;
        K key = p.key;
        removeNode(hash(key), key, null, false, false);
        expectedModCount = modCount;
    }
}
点击复制代码复制出错复制成功
```

### [PS：ConcurrentModificationException是什么？](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=ps：concurrentmodificationexception是什么？)

根据ConcurrentModificationException的文档介绍，一些对象不允许并发修改，当这些修改行为被检测到时，就会抛出这个异常。（例如一些集合不允许一个线程一边遍历时，另一个线程去修改这个集合）。

一些集合（例如Collection, Vector, ArrayList，LinkedList, HashSet, Hashtable, TreeMap, AbstractList, Serialized Form）的Iterator实现中，如果提供这种并发修改异常检测，那么这些Iterator可以称为是"fail-fast Iterator"，意思是快速失败迭代器，就是检测到并发修改时，直接抛出异常，而不是继续执行，等到获取到一些错误值时在抛出异常。

异常检测主要是通过modCount和expectedModCount两个变量来实现的，

- modCount 集合被修改的次数，一般是被集合(ArrayList之类的)持有，每次调用add()，remove()方法会导致modCount+1
- expectedModCount 期待的modCount，一般是被Iterator(ArrayList.iterator()方法返回的iterator对象)持有，一般在Iterator初始化时会赋初始值，在调用Iterator的remove()方法时会对expectedModCount进行更新。（可以看看上面的ArrayList.Itr源码）

然后在Iterator调用next()遍历元素时，会调用checkForComodification()方法比较modCount和expectedModCount，不一致就抛出ConcurrentModificationException。

单线程操作Iterator不当时也会抛出ConcurrentModificationException异常。（上面的例子就是）

#### [总结](http://notfound9.github.io/interviewGuide/#/docs/HashMap?id=总结)

因为ArrayList和HashMap的Iterator都是上面所说的“fail-fast Iterator”，Iterator在获取下一个元素，删除元素时，都会比较expectedModCount和modCount，不一致就会抛出异常。

所以当使用Iterator遍历元素(for-each遍历底层实现也是Iterator)时，需要删除元素，一定需要使用 **Iterator的remove()方法** 来删除，而不是直接调用ArrayList或HashMap自身的remove()方法,否则会导致Iterator中的expectedModCount没有及时更新，之后获取下一个元素或者删除元素时，expectedModCount和modCount不一致，然后抛出ConcurrentModificationException异常。



### 谈一谈你对LinkedHashMap的理解？

LinkedHashMap是HashMap的子类，与HashMap的实现基本一致，只是说在HashMap的基础上做了一些扩展，所有的节点都有一个before指针和after指针，根据插入顺序形成一个**双向链表**。默认accessOrder是false，也就是按照**插入顺序**来排序的，每次新插入的元素都是插入到链表的末尾。map.keySet().iterator().next()第一个元素是最早插入的元素的key。LinkedHashMap可以用来实现LRU算法。(accessOrder为true，会按照访问顺序来排序。)

![img](http://notfound9.github.io/interviewGuide/static/249993-20161215143120620-1544337380-20201130113344624.png)LRU算法实现：

```java
//使用LinkedHashMap实现LRU算法(accessOrder为false的实现方式)
// LinkedHashMap默认的accessOrder为false，也就是会按照插入顺序排序，
// 所以在插入新的键值对时，总是添加在队列尾部，
// 如果是访问已存在的键值对，或者是put操作的键值对已存在，那么需要将键值对先移除再添加。
public class LRUCache{
    int capacity;
    Map<Integer, Integer> map;
    public LRUCache(int capacity) {
        this.capacity = capacity;
        map = new LinkedHashMap<>();
    }
    public int get(int key) {
        if (!map.containsKey(key)) { return -1; }
        //先删除旧的位置，再放入新位置
        Integer value = map.remove(key);
        map.put(key, value);
        return value;
    }
    public void put(int key, int value) {
        if (map.containsKey(key)) {
            map.remove(key);
            map.put(key, value);
            return;
        }
        //超出capacity，删除最久没用的,利用迭代器，删除第一个
        if (map.size() > capacity) {
      map.remove(map.keySet().iterator().next());
        }
        map.put(key, value);
    }
}
```



**下面是另外一种实现方法：**

```java
//使用LinkedHashMap实现LRU算法(accessOrder为true的实现方式)
//如果是将accessOrder设置为true，get和put已有键值对时就不需要删除key了
public static class LRUCache2 {
    int capacity;
    LinkedHashMap<Integer, Integer> linkedHashMap;
    LRUCache2(int capacity) {
      this.capacity = capacity;
      linkedHashMap = new LinkedHashMap<Integer, Integer>(16,0.75f,true);
    }
    public int get(int key) {
      Integer value = linkedHashMap.get(key);
      return value == null ? -1 : value;
    }
    public void put(int key, int val) {
      Integer value = linkedHashMap.get(key);
      linkedHashMap.put(key, val);
      if (linkedHashMap.size() > capacity) {
       linkedHashMap.remove(linkedHashMap.keySet().iterator().next());
      }
    }
}点击复制代码复制出错复制成功
```



#### LinkedHashMap是怎么保存节点的插入顺序或者访问顺序的呢？

默认accessOrder为false，保存的是插入顺序，插入时调用的还是父类HashMap的putVal()方法，在putVal()中创建新节点时是会调用newNode()方法来创建一个节点，在newNode()方法中会调用linkNodeLast()方法将节点添加到双向链表的尾部。

```java
final V putVal(int hash, K key, V value, boolean onlyIfAbsent,
                   boolean evict) {
//省略了部分代码...
tab[i] = newNode(hash, key, value, null);
//省略了部分代码...
}
//创建新节点
Node<K,V> newNode(int hash, K key, V value, Node<K,V> e) {
        LinkedHashMap.Entry<K,V> p = new LinkedHashMap.Entry<K,V>(hash, key, value, e);
        linkNodeLast(p);
        return p;
}
//移动到双向链表尾部
private void linkNodeLast(LinkedHashMap.Entry<K,V> p) {
    LinkedHashMap.Entry<K,V> last = tail;
    tail = p;
    if (last == null) head = p;
    else {
            p.before = last;
            last.after = p;
    }
}
```



如果accessOrder为true，会保存访问顺序，在访问节点时，会调用afterNodeAccess()方法将节点先从双向链表移除，然后添加到链表尾部。

```java
public class LinkedHashMap<K,V>
    extends HashMap<K,V>
    implements Map<K,V>
{
//头结点，指向最老的元素
    transient LinkedHashMap.Entry<K,V> head;
//尾节点，指向最新的元素
    transient LinkedHashMap.Entry<K,V> tail;
//如果accssOrder为true，代表节点需要按照访问顺序排列，每次访问了元素，会将元素移动到尾部（代表最新的节点）。
public V get(Object key) {
        Node<K,V> e;
        if ((e = getNode(hash(key), key)) == null)
            return null;
        if (accessOrder)
            afterNodeAccess(e);
        return e.value;
}
//将节点从双向链表中删除，移动到尾部。
void afterNodeAccess(Node<K,V> e) { // move node to last
        LinkedHashMap.Entry<K,V> last;
        if (accessOrder && (last = tail) != e) {
            LinkedHashMap.Entry<K,V> p =
                (LinkedHashMap.Entry<K,V>)e, 
            b = p.before, a = p.after;
            p.after = null;
            if (b == null) head = a;
            else b.after = a;
            if (a != null) a.before = b;
            else last = b;
            if (last == null) head = p;
            else {
                p.before = last;
                last.after = p;
            }
            tail = p;
            ++modCount;
        }
    }
}
```



## TreeMap