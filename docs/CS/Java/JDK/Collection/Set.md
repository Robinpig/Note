## Introduction

`Set` 是 `Collection` 的「不含重复元素」子接口：它的方法签名与 `Collection` 完全一致，但**对 `add` 加了约束**——不允许存在 `e1.equals(e2)` 的两个元素，最多允许一个 `null`。同时要求：若把可变对象作为元素放进 `Set`，改变其参与 `equals` / `hashCode` 的字段会破坏集合的不变式，这一条由调用方自己保证。

与 `List` 的三个关键差异：

1. **无位置**：`Set` 没有 `get(int)`。是否「有序」是实现类的属性而不是接口属性——`HashSet` 无序、`LinkedHashSet` 保持插入序、`TreeSet` 按比较器序、`EnumSet` 按 `ordinal` 序。JDK 21 起这类「有确定遭遇顺序」的集合统一由 [SequencedSet](/docs/CS/Java/JDK/Collection/Collection.md?id=sequenced) 表达。
2. **`equals` 按集合语义**：`AbstractSet.equals` 只要求「同为 `Set`、size 相同、`containsAll` 成立」，因此 `new HashSet<>(List.of(1,2)).equals(new TreeSet<>(List.of(2,1)))` 为 `true`，而与任何 `List` 比较必为 `false`。
3. **`hashCode` 是元素 hash 之和**：与遍历顺序无关，保证跨实现一致。

> [!WARNING]
>
> `java.util.BitSet` **不是** `Set`——它不实现 `Set` 接口，只是一个可增长的位向量，与集合框架无继承关系，仅因历史原因同页收录（见文末 [BitSet](#bitset)）。

## Set Interface

`Set` 在 JDK 9 起多了静态工厂，JDK 10 起多了 `copyOf`：

```java
public interface Set<E> extends Collection<E> {
    // Query Operations
    int size();
    boolean isEmpty();
    boolean contains(Object o);
    Iterator<E> iterator();
    Object[] toArray();

    // Modification Operations
    boolean add(E e);
    boolean remove(Object o);

    // Bulk Operations
    boolean containsAll(Collection<?> c);
    boolean retainAll(Collection<?> c);
    boolean removeAll(Collection<?> c);
    void clear();

    // Comparison and hashing
    boolean equals(Object o);
    int hashCode();

    // since 9：不可变集合工厂
    static <E> Set<E> of() { return ImmutableCollections.emptySet(); }
    static <E> Set<E> of(E e1) { return new ImmutableCollections.Set12<>(e1); }
    // ... of(E e1 .. E e10) 共 10 个重载，逐个消除 varargs 数组分配
    static <E> Set<E> of(E... elements) { ... }   // 第 11 个：varargs 兜底

    // since 10：从已有集合快照出不可变副本
    static <E> Set<E> copyOf(Collection<? extends E> coll) { ... }

    @Override
    default Spliterator<E> spliterator() { ... }
}
```

`of()` 做十份重载的理由和 `List.of` 一样：**避免每次调用分配 varargs 数组**，超过 10 个才落到 `@SafeVarargs` 的 `of(E...)`。

## AbstractSet

`AbstractSet` 相对 `AbstractCollection` 只多做了三件事：`equals`、`hashCode`、`removeAll`。

```java
public boolean equals(Object o) {
    if (o == this)
        return true;
    if (!(o instanceof Set))       // 先判是不是 Set，List 直接出局
        return false;
    Collection<?> c = (Collection<?>) o;
    if (c.size() != size())
        return false;
    try {
        return containsAll(c);
    } catch (ClassCastException | NullPointerException unused) {
        return false;              // 元素类型不兼容视为不等，而不是抛出去
    }
}

public int hashCode() {
    int h = 0;
    Iterator<E> i = iterator();
    while (i.hasNext()) {
        E obj = i.next();
        if (obj != null)
            h += obj.hashCode();
    }
    return h;                      // 求和，与遍历顺序无关
}
```

`removeAll` 有一个容易被忽略的优化：**永远遍历「小的那一边」**。

```java
public boolean removeAll(Collection<?> c) {
    Objects.requireNonNull(c);
    boolean modified = false;

    if (size() > c.size()) {
        for (Object e : c)             // 参数更小：逐个 remove
            modified |= remove(e);
    } else {
        for (Iterator<?> i = iterator(); i.hasNext(); ) {  // 自身更小：迭代 + iterator.remove()
            if (c.contains(i.next())) {
                i.remove();
                modified = true;
            }
        }
    }
    return modified;
}
```

实际后果：**复杂度取决于哪一边 size 更小，而不是哪一边查询更快**——参数集合更大时会走「迭代自身 + 逐个 `c.contains()`」这条分支，对 `TreeSet` 而言可能比直接 `remove` 更慢。

## HashSet

`HashSet` 是 `HashMap` 的一层薄包装：**元素存在 key 上，value 统一填一个静态哨兵对象**。

```java
public class HashSet<E>
    extends AbstractSet<E>
    implements Set<E>, Cloneable, java.io.Serializable
{
    transient HashMap<E,Object> map;

    // Dummy value to associate with an Object in the backing Map
    static final Object PRESENT = new Object();
```

于是全部操作都退化为 `HashMap` 调用，`add` 的返回值靠「put 是否返回 null」判定：

```java
public boolean add(E e) {
    return map.put(e, PRESENT)==null;
}

public boolean remove(Object o) {
    return map.remove(o)==PRESENT;
}

public boolean contains(Object o) {
    return map.containsKey(o);
}

public void clear() {
    map.clear();
}
```

所以 `HashSet` 的时间/空间复杂度、扩容策略、树化阈值（`TREEIFY_THRESHOLD = 8`）、负载因子（0.75）**完全等于 [HashMap](/docs/CS/Java/JDK/Collection/Map.md?id=hashmap)**，这里不重复。

### Capacity

```java
public HashSet(int initialCapacity, float loadFactor) {
    map = new HashMap<>(initialCapacity, loadFactor);
}

public HashSet(int initialCapacity) {
    map = new HashMap<>(initialCapacity);
}

public HashSet() {
    map = new HashMap<>();          // 16 / 0.75
}

public HashSet(Collection<? extends E> c) {
    map = new HashMap<>(Math.max((int) (c.size()/.75f) + 1, 16));
    addAll(c);
}
```

⚠️ 两个坑：

1. `new HashSet<>(n)` 里的 `n` 是 **HashMap 的桶数组容量**而不是「预计元素个数」。要放 1000 个元素且不扩容，得写 `new HashSet<>((int)(1000/0.75f)+1)`。JDK 19 起给了语义正确的工厂：

```java
// since 19
public static <T> HashSet<T> newHashSet(int numElements) {
    return new HashSet<>(HashMap.newHashMap(numElements));
}
```

2. `HashSet(Collection)` 的容量计算里 `Math.max(..., 16)` 意味着**用一个空集合构造 `HashSet`，底层数组也是 16**，不是 0。这是 JDK 的实际行为，别指望 `new HashSet<>(smallSet)` 省内存。

### Clone

`clone()` 是**浅拷贝**：复制桶数组结构与引用，不复制元素对象本身。

```java
public Object clone() {
    try {
        HashSet<E> newSet = (HashSet<E>) clone();
        newSet.map = (HashMap<E, Object>) map.clone();
        return newSet;
    } catch (CloneNotSupportedException e) {
        throw new InternalError(e);
    }
}
```

## LinkedHashSet

`LinkedHashSet` 继承 `HashSet`，底层换成 `LinkedHashMap`，多维护一条**贯穿所有节点的双向链表**来固定迭代顺序。

```java
public class LinkedHashSet<E>
    extends HashSet<E>
    implements SequencedSet<E>, Cloneable, java.io.Serializable {

    public LinkedHashSet(int initialCapacity, float loadFactor) {
        super(initialCapacity, loadFactor, true);   // 第三个参数 dummy：选中 LinkedHashMap 构造器
    }

    public LinkedHashSet() {
        super(16, .75f, true);
    }

    public LinkedHashSet(Collection<? extends E> c) {
        super(HashMap.calculateHashMapCapacity(Math.max(c.size(), 12)), .75f, true);
        addAll(c);
    }
}
```

`super(int, float, boolean)` 是 `HashSet` 的**包级私有构造器**，那个 `boolean` 没有任何逻辑作用，纯粹是为了让重载决议挑中「造 `LinkedHashMap`」的那条分支：

```java
// HashSet.java
HashSet(int initialCapacity, float loadFactor, boolean dummy) {
    map = new LinkedHashMap<>(initialCapacity, loadFactor);
}
```

代价是每个节点多两个引用（`before` / `after`），换来 `O(1)` 的插入序迭代；`contains` 仍是 `O(1)`——它先走哈希表，不是遍历链表。

### SequencedSet

JDK 21 起 `LinkedHashSet` 实现 `SequencedSet`，于是不再需要「先转 `List` 再倒着遍历」这种写法：

```java
public SequencedSet<E> reversed() {
    return new SequencedSet<>() {
        public Iterator<E> iterator() { return map().sequencedKeySet().reversed().iterator(); }
        public int size()             { return LinkedHashSet.this.size(); }
        public SequencedSet<E> reversed() { return LinkedHashSet.this; }   // 反向的反向 = 自身
        // add(e) 落到 addFirst：往反转视图里加元素 = 插到原集合头部
    };
}
```

注意 `reversed()` 返回的是**视图而不是副本**：对它的结构性修改会写回原集合，`add` 等价于原集合的 `addFirst`（`map().putFirst(e, PRESENT)`）。

## TreeSet

`TreeSet` 底层是 `TreeMap`（红黑树），元素存在 key 上，value 同样填 `PRESENT`。

```java
public class TreeSet<E> extends AbstractSet<E>
    implements NavigableSet<E>, Cloneable, java.io.Serializable
{
    private transient NavigableMap<E,Object> m;
    private static final Object PRESENT = new Object();

    TreeSet(NavigableMap<E,Object> m) { this.m = m; }

    public TreeSet() {
        this(new TreeMap<>());
    }

    public TreeSet(Comparator<? super E> comparator) {
        this(new TreeMap<>(comparator));
    }
}
```

JDK 21 起 `NavigableSet` 继承 `SequencedSet`，所以 `TreeSet` 天然拥有 `getFirst` / `getLast` / `addFirst` / `removeLast` / `reversed()`，且 `first()` 与 `getFirst()` 等价——JDK 把这两套 API 统一了。

### NavigableSet

`NavigableSet` 相对 `SortedSet` 多出的是「找最近邻」与「半开区间」能力：

| 方法                           | 语义                       |
| :--------------------------- | :----------------------- |
| `lower(e)` / `floor(e)`      | `<e` / `<=e` 的最大元素       |
| `higher(e)` / `ceiling(e)`   | `>e` / `>=e` 的最小元素       |
| `pollFirst()` / `pollLast()` | 取出并移除最小 / 最大元素          |
| `descendingSet()`            | 反向视图（`reversed()` 的前身）   |
| `subSet(e, fromInc, toExc)`  | JDK 21 起的重载，可分别指定两端是否闭合  |
| `headSet(e, inclusive)`      | 同上                      |
| `tailSet(e, inclusive)`      | 同上                      |

区间视图同样是**视图**：对 `subSet` 结果 `add` 越界元素会抛 `IllegalArgumentException`，且原集合的改动会实时反映在视图里。

> [!WARNING]
>
> **`TreeSet` 判重用的是 `compareTo` / `compare`，不是 `equals`。** 若 `Comparator.compare(a,b)==0` 但 `a.equals(b)==false`，第二个元素会被静默丢弃；反过来若 `compare!=0` 而 `equals==true`，集合里会出现「相等」元素。这与 `Set` 接口的通用契约不一致（`Set` 的 Javadoc 明确写了 `TreeSet` 是例外），用 `TreeSet` 时必须保证比较器与 `equals` 一致。

## EnumSet

`EnumSet` 是集合框架里最特殊的一个：**它不存元素，只存一个位向量**，第 `i` 位表示 `ordinal == i` 的枚举常量是否在集合中。

JDK 21 起它被改成 `sealed`，两个实现都是包级私有的顶层类，外部无法再扩展：

```java
public abstract sealed class EnumSet<E extends Enum<E>> extends AbstractSet<E>
    implements Cloneable, java.io.Serializable permits JumboEnumSet, RegularEnumSet
{
    final transient Class<E> elementType;
    final transient Enum<?>[] universe;      // 缓存该 enum 的全部常量

    public static <E extends Enum<E>> EnumSet<E> noneOf(Class<E> elementType) {
        Enum<?>[] universe = getUniverse(elementType);
        if (universe == null)
            throw new ClassCastException(elementType + " not an enum");

        if (universe.length <= 64)
            return new RegularEnumSet<>(elementType, universe);
        else
            return new JumboEnumSet<>(elementType, universe);
    }
}
```

分界线是 **64**：枚举常量数 `<= 64` 用 `RegularEnumSet`（一个 `long`），否则用 `JumboEnumSet`（`long[]`）。

### RegularEnumSet

```java
final class RegularEnumSet<E extends Enum<E>> extends EnumSet<E> {
    private long elements = 0L;

    public int size() {
        return Long.bitCount(elements);            // 单条指令
    }

    // contains: (elements & (1L << ordinal)) != 0
    public boolean contains(Object e) { ... }

    public boolean add(E e) {
        typeCheck(e);
        long oldElements = elements;
        elements |= (1L << ((Enum<?>)e).ordinal());
        return elements != oldElements;            // 用「有没有变」判定是否新增
    }

    // remove: elements &= ~(1L << ordinal)
    public boolean remove(Object e) { ... }
}
```

`contains` / `add` / `remove` 全是 `O(1)` 位运算，`size()` 是 `Long.bitCount`，且不分配任何节点对象——**这是 JDK 里最省内存的 `Set`**。

### JumboEnumSet

```java
final class JumboEnumSet<E extends Enum<E>> extends EnumSet<E> {
    private long[] elements;

    JumboEnumSet(Class<E>elementType, Enum<?>[] universe) {
        super(elementType, universe);
        elements = new long[(universe.length + 63) >>> 6];   // 按 64 位一个 word 向上取整
    }
}
```

操作退化成「定位 word + 位运算」，`contains` 仍是 `O(1)`，但不再是单条指令。

### Ordering

`EnumSet` 的迭代顺序固定为**枚举常量的声明顺序**（即 `ordinal` 升序），这一点由 `universe` 数组保证，不受 `SALT` 随机化影响（对比 [Immutable Sets](#immutable-sets)）。

常用工厂：

```java
EnumSet.noneOf(DayOfWeek.class)            // 空集
EnumSet.allOf(DayOfWeek.class)             // 全集
EnumSet.of(MONDAY, TUESDAY)                // 1~5 个有专用重载，第 6 个是 varargs
EnumSet.range(MONDAY, FRIDAY)              // 闭区间
EnumSet.complementOf(weekend)              // 补集
EnumSet.copyOf(collection)                 // 从集合拷（空集合需传 EnumSet 或先判空）
```

> [!WARNING]
>
> `EnumSet.copyOf(Collection)` 对**空且非 `EnumSet`** 的集合会抛 `IllegalArgumentException`——它没法从一个空集合推断元素类型。这时只能显式 `EnumSet.noneOf(Xxx.class)`。






## CopyOnWriteArraySet

`CopyOnWriteArraySet` 是 `CopyOnWriteArrayList` 的 `Set` 包装，靠**写时复制数组**实现无锁读：

```java
public class CopyOnWriteArraySet<E> extends AbstractSet<E>
        implements java.io.Serializable {

    private final CopyOnWriteArrayList<E> al;

    public CopyOnWriteArraySet() {
        al = new CopyOnWriteArrayList<E>();
    }

    public CopyOnWriteArraySet(Collection<? extends E> c) {
        if (c.getClass() == CopyOnWriteArraySet.class) {
            // 同类型：直接复用底层数组，省一次拷贝
            CopyOnWriteArraySet<E> cc = (CopyOnWriteArraySet<E>)c;
            al = new CopyOnWriteArrayList<E>(cc.al);
        } else {
            al = new CopyOnWriteArrayList<E>();
            al.addAllAbsent(c);          // 逐元素 addIfAbsent
        }
    }

    public int size() { return al.size(); }

    public boolean add(E e) {
        return al.addIfAbsent(e);        // 存在则不加，整体仍是「复制 + 替换」
    }

    public boolean remove(Object o) { return al.remove(o); }
}
```

关键性质：

- **读完全无锁**：`contains` / 迭代都基于 `volatile` 数组快照，不需要加锁，也不会抛 `ConcurrentModificationException`。
- **写代价是 `O(n)`**：每次 `add` 都要复制整个数组（底层 `Arrays.copyOf`），因此只适合**读远多于写、且规模小**的场景（监听器列表、配置白名单这类）。
- 迭代期间看到的是**发起迭代那一刻的快照**，之后其他线程的写入对本次迭代不可见。

> [!WARNING]
>
> 它不是「并发 HashSet」。100 万元素的 `CopyOnWriteArraySet` 每加一个元素就要复制 100 万个引用——高频写入下会瞬间打爆 GC。高并发大集合请用 `ConcurrentHashMap.newKeySet()`。

## ConcurrentSkipListSet

`ConcurrentSkipListSet` 底层是 `ConcurrentSkipListMap`（跳表），元素作 key，value 填 `Boolean.TRUE`：

```java
public class ConcurrentSkipListSet<E>
    extends AbstractSet<E>
    implements NavigableSet<E>, Cloneable, java.io.Serializable {

    private final ConcurrentNavigableMap<E,Object> m;

    public ConcurrentSkipListSet() {
        m = new ConcurrentSkipListMap<>();
    }

    public boolean add(E e) {
        return m.putIfAbsent(e, Boolean.TRUE) == null;   // CAS 语义的 putIfAbsent
    }
}
```

定位：**并发环境下的有序 `Set`**。`contains` / `add` / `remove` 均摊 `O(log n)`，全无锁（CAS），迭代弱一致（不抛 `ConcurrentModificationException`），且继承了 `NavigableSet` 的全部区间与最近邻操作。

对比几个常见误用：

| 需求            | 别用                                             | 该用                                  |
| :------------ | :--------------------------------------------- | :---------------------------------- |
| 并发无序去重        | `Collections.synchronizedSet(new HashSet<>())`  | `ConcurrentHashMap.newKeySet()`     |
| 并发有序去重        | 加锁的 `TreeSet`                                   | `ConcurrentSkipListSet`             |
| 读多写少、需要无锁迭代   | `HashSet`                                      | `CopyOnWriteArraySet`（仅小规模）         |

## Wrappers

### newSetFromMap

`Collections.newSetFromMap` 把任意 `Map<E, Boolean>` 的 keySet 包装成 `Set`——这是**自建特殊语义 `Set` 的唯一官方入口**（比如带弱引用 / 并发语义的 set）：

```java
public static <E> Set<E> newSetFromMap(Map<E, Boolean> map) {
    if (! map.isEmpty()) // implicit null check
        throw new IllegalArgumentException("Map is non-empty");
    return new SetFromMap<>(map);
}

private static class SetFromMap<E> extends AbstractSet<E>
    implements Set<E>, Serializable
{
    final Map<E, Boolean> m;          // The backing map
    private transient Set<E> s;       // Its keySet

    SetFromMap(Map<E, Boolean> map) {
        m = map;
        s = map.keySet();
    }

    public boolean add(E e)          { return m.put(e, Boolean.TRUE) == null; }
    public boolean remove(Object o)  { return m.remove(o) != null; }
    public boolean contains(Object o){ return m.containsKey(o); }
    public Iterator<E> iterator()    { return s.iterator(); }
    public boolean equals(Object o)  { return o == this || s.equals(o); }
}
```

两个约束：**传入的 map 必须是空的**（否则 `IllegalArgumentException`），且**之后不要再直接操作这个 map**（`Set` 与 map 是同一份数据）。典型用法：

```java
Set<Object> weakHashSet = Collections.newSetFromMap(new WeakHashMap<>());
```

### Synchronized & Unmodifiable

`Collections` 的包装与不可变工厂语义差别很大：

| 方法                               | 语义                                              | 源集合后续被改       |
| :------------------------------- | :---------------------------------------------- | :------------ |
| `Collections.synchronizedSet(s)` | **视图**：所有方法加锁（`synchronized` 块）                 | 会反映；迭代需手动加锁   |
| `Collections.unmodifiableSet(s)` | **视图**：写方法抛 `UnsupportedOperationException`      | 会反映           |
| `Set.copyOf(s)`                  | **快照**：拷贝一份，与源集合彻底解耦                             | 不会            |

`unmodifiableSet` 是「包一层壳」而不是「冻结」——原集合改了它跟着变，想真正隔离必须用 `Set.copyOf`。

## Immutable Sets

`Set.of(...)` / `Set.copyOf(...)` 返回 `ImmutableCollections` 里的私有实现，按规模分两种：

```java
static final class Set12<E> extends AbstractImmutableSet<E> {   // 1~2 个元素，字段直接存
    private final E e0;
    private final E e1;   // 单元素时为 EMPTY 哨兵
}

static final class SetN<E> extends AbstractImmutableSet<E> {    // 3+ 个元素，开放寻址表
    @Stable final E[] elements;
    @Stable final int size;

    SetN(E... input) {
        size = input.length;
        elements = (E[])new Object[EXPAND_FACTOR * input.length];   // EXPAND_FACTOR = 2，负载 0.5
        for (int i = 0; i < input.length; i++) {
            E e = input[i];
            int idx = probe(e);                                     // implicit nullcheck of e
            if (idx >= 0) {
                throw new IllegalArgumentException("duplicate element: " + e);
            } else {
                elements[-(idx + 1)] = e;
            }
        }
    }
}
```

三个必须记住的行为：

1. **不接受 `null`**：构造时即 `NullPointerException`（`HashSet` 反而允许一个 `null`）。
2. **重复元素抛 `IllegalArgumentException`**：`Set.of(1, 1, 2)` 直接炸，不像 `HashSet` 那样静默去重。想去重得先 `new HashSet<>(...)` 再 `Set.copyOf`。
3. **负载因子固定 0.5**：`EXPAND_FACTOR = 2`，容量恒为元素数的两倍，用空间换 `probe` 的探测长度。

### Iteration Order

不可变 `Set` / `Map` 的迭代顺序**每次 JVM 启动都不同**，由启动时生成的一个随机 salt 决定：

```java
private static final long SALT32L;
private static final boolean REVERSE;
static {
    long color = 0x243F_6A88_85A3_08D3L;      // slice of pi
    long seed = CDS.getRandomSeedForDumping();
    if (seed == 0) {
        seed = System.nanoTime();
    }
    SALT32L = (int)((color * seed) >> 16) & 0xFFFF_FFFFL;
    REVERSE = (SALT32L & 1) == 0;             // 最低位决定是否反向遍历
}
```

迭代器从「salt 决定的随机下标」开始，按 `REVERSE` 决定前进还是后退：

```java
SetNIterator() {
    remaining = size;
    // pick a starting index in the [0 .. element.length-1] range randomly based on SALT32L
    idx = (int) ((SALT32L * elements.length) >>> 32);
}
```

这是 **JDK 刻意的防御性设计**：防止业务代码意外依赖 `Set.of` 的迭代顺序（一旦形成依赖，JDK 就无法再调整内部布局）。所以**永远不要指望 `Set.of(...)` 的遍历顺序稳定**，需要顺序就用 `LinkedHashSet` 或先排序。

## Summary

| 实现                      | 底层结构              | 顺序           | `add`/`contains` | 允许 null | 线程安全       |
| :---------------------- | :---------------- | :----------- | :--------------- | :----- | :--------- |
| `HashSet`               | `HashMap`         | 无            | `O(1)` 均摊        | 是      | 否          |
| `LinkedHashSet`         | `LinkedHashMap`   | 插入序          | `O(1)` 均摊        | 是      | 否          |
| `TreeSet`               | `TreeMap` 红黑树     | 比较器序         | `O(log n)`       | 否      | 否          |
| `EnumSet`               | `long` / `long[]` | `ordinal` 序  | `O(1)`           | 否      | 否          |
| `CopyOnWriteArraySet`   | `Object[]`        | 插入序          | `O(n)` / `O(n)`  | 是      | 是（写复制）     |
| `ConcurrentSkipListSet` | 跳表                | 比较器序         | `O(log n)`       | 否      | 是（CAS）     |
| `Set.of(...)`           | 开放寻址表             | **随机**       | `O(1)` 均摊        | 否      | 不可变，天然安全   |

选型判断链：**元素是不是枚举** → `EnumSet`；**要不要顺序** → 插入序用 `LinkedHashSet`、排序用 `TreeSet`；**要不要并发** → 无序用 `ConcurrentHashMap.newKeySet()`、有序用 `ConcurrentSkipListSet`；**只是想建一个常量集合** → `Set.of`。剩下的默认 `HashSet`。


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

- [List](/docs/CS/Java/JDK/Collection/List.md)
- [Queue](/docs/CS/Java/JDK/Collection/Queue.md)
- [WeakHashMap](/docs/CS/Java/JDK/Collection/WeakHashMap.md)
- [JDK](/docs/CS/Java/JDK/JDK.md)

## References

1. [Set (Java SE 25 & JDK 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/Set.html)
2. [EnumSet (Java SE 25 & JDK 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/EnumSet.html)
3. [Collections (Java SE 25 & JDK 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/Collections.html)
4. [JEP 431: Sequenced Collections](https://openjdk.org/jeps/431)
5. [Java Collections Framework Overview](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/package-summary.html)
