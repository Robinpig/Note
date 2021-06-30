## Introduction

WeakHashMap的行为一定程度上基于垃圾收集器的行为，因此一些Map数据结构对应的常识在WeakHashMap上会失效——size()方法的返回值会随着程序的运行变小，isEmpty()方法的返回值会从false变成true等等。

```java
 public class WeakHashMap<K,V>
     extends AbstractMap<K,V>
     implements Map<K,V> {
```

## Fields

```java
 Entry<K,V>[] table;  //底层采用数组+单向链表
 private int size;  //保存的节点数
 private int threshold;  //size超过此阀值时，需要resize，扩容2倍
 private final float loadFactor;  //负载因子
 private final ReferenceQueue<Object> queue = new ReferenceQueue<>();  //保存的是“已被GC清除”的“弱引用的键”
 int modCount;  //用来帮助实现fail-fast机制
```

WeakHashMap实际上是用**Entry数组**来存储数据的，它存储的内容也是键值对(key-value)映射，而且键和值都可以是null。


Entry<K,V>[] table;

Entry类的结构如下：

private static class Entry<K,V> extends WeakReference<Object> implements Map.Entry<K,V>

WeakHashMap的键是“**弱键**”。在 WeakHashMap 中，当某个键不再正常使用时，会被从WeakHashMap中自动移除。更精确地说，对于一个给定的键，其映射的存在并不阻止垃圾回收器对该键的丢弃，这就使该键成为可终止的，然后被终止并回收。某个键被终止时，它对应的键值对也就从映射中有效地移除了。
这个“弱键”的原理呢？大致上就是，通过WeakReference和ReferenceQueue实现的。



## 关于Java中的引用类型

引用类型主要分为4种：
①强引用（Strong Reference）就是永远不会回收掉被引用的对象，比如说我们代码中new出来的对象。
②软引用（SoftReference）表示有用但是非必需的，如果系统内存资源紧张，可能就会被回收。
③弱引用（WeakReference）表示非必需的对象，只能存活到下一次垃圾回收发生之前。
④虚引用（PhantomReference）是最弱的，这个引用无法操作对象。

WeakHashMap中用WeakReference，也就是**弱引用**来实现。



##  引用队列ReferenceQueue

引用队列相当于一个电话簿一样的东西，用于监听和管理在引用对象中被回收的对象。

下面帮助理解ReferenceQueue 的demo。

```java
 public class ReferenceTest {
     private static final int _1MB = 1024*1024;//设置大小为1MB
  
     public static void main(String[] args) throws InterruptedException {
         ReferenceQueue<Object> referenceQueue = new ReferenceQueue<Object>();//用引用队列进行监控引用的回收情况
         Object value = new Object();
         Map<Object, Object> map = new HashMap<Object, Object>();
         for (int i = 0; i < 100; i++) {//循环100次把数据插入到弱应用中（WeakReference）， 同时把弱引用作为key存入HashMap
             byte[] bytes = new byte[_1MB];
             //每个引用中都有关联引用队列（referenceQueue）的构造器，用引用队列监听回收情况
             //如此，那么每次WeakReference中的bytes被回收之后，那么这个weakReference对象就会放入引用队列
             WeakReference<byte[]> weakReference = new WeakReference<byte[]>(bytes, referenceQueue);
             map.put(weakReference, value);
         }
  
         Thread thread = new Thread(new Runnable() {//线程通过调用引用队列的情况查看那些对象被回收
             @SuppressWarnings("unchecked")
             public void run() {
                 try {
                     int cnt = 0;
                     WeakReference<byte[]> k;
                     while ((k = (WeakReference<byte[]>) referenceQueue.remove()) != null) {//返回被回收对象的引用（注意本例中被回收的是bytes）
                         System.out.println((cnt++)+"回收了"+k);
                         System.out.println("map的size = " + map.size());//用于监控map的存储数量有没有发生变化
                     }
                 } catch (Exception e) {
                     // TODO: handle exception
                 }
             }
         });
  
         thread.start();
     }
  
 }
```

部分输出如下。

```java
 85回收了java.lang.ref.WeakReference@610455d6
 map的size = 100
 86回收了java.lang.ref.WeakReference@2503dbd3
 map的size = 100
 87回收了java.lang.ref.WeakReference@45ee12a7
 map的size = 100
 88回收了java.lang.ref.WeakReference@4554617c
 map的size = 100
 89回收了java.lang.ref.WeakReference@266474c2
 map的size = 100
 90回收了java.lang.ref.WeakReference@74a14482
 map的size = 100
```

梳理一下流程。

1、bytes对象存入到weakReference对象中。
2、weakReference对象作为key，一个Object作为值存入HashMap中。
3、GC回收了bytes对象，这个时候就要把引用这个对象的weakReference对象存储到ReferenceQueue中。
4、死循环ReferenceQueue， 打印出被回收的对象。
在这里，jvm回收了弱引用bytes，但没有回收作为map中的key的weakReference，因此每次我们打印的size都是100。



上面这个逻辑就是核心WeakHashMap的实现，WeakHashMap只不过比上述的代码多了一步：把引用回收的对象从Map中移除罢了。

### 实现弱键

ReferenceQueue是一个队列，它会保存被GC回收的“弱键”。实现步骤是：

-  新建WeakHashMap，将“键值对”添加到WeakHashMap中。
   实际上，WeakHashMap是通过数组table保存Entry(键值对)；每一个Entry实际上是一个单向链表，即Entry是键值对链表。
- 当某“弱键”不再被其它对象引用，并被GC回收时。在GC回收该“弱键”时，这个“弱键”也同时会被添加到ReferenceQueue(queue)队列中。

- 当下一次我们需要操作WeakHashMap时，会先同步table和queue。table中保存了全部的键值对，而queue中保存被GC回收的键值对；同步它们，就是删除table中被GC回收的键值对。
  这就是“弱键”如何被自动从WeakHashMap中删除的步骤了。



测试demo如下。

```java
 public class WeakTest {
     private static final int _1MB = 1024 * 1024;//设置大小为1MB
  
     public static void main(String[] args) throws InterruptedException {
         Object value = new Object();
         WeakHashMap<Object, Object> map = new WeakHashMap<Object, Object>();
         for (int i = 0; i < 100; i++) {//循环100次把数据插入WeakHashMap中
             byte[] bytes = new byte[_1MB];
             map.put(bytes, value);
         }
         while (true) {//死循环监控map大小变化
             Thread.sleep(500);//稍稍停顿，效果更直观
             System.out.println(map.size());//打印WeakHashMap的大小
             System.gc();//建议系统进行GC
         }
     }
 }
```

执行结果。

```java
 9
 0
 0
 0
 .......
```

其实当我们在循环100次添加数据时，就已经开始回收弱引用了，因此我们会看到第一次打印的size是9，而不是100，在打印了大小之后，建议系统（System.gc()）发起一次GC操作，为什么说是建议呢？因为系统不一定会接收到你指令就会发生GC的。一旦GC发生，那么弱引用就会被清除，导致WeakHashMap的大小为0。 同时，值得一提的是，存在WeakHashMap中的数据，并不会平白无故就给你移除了map中的数据，必然是你触发了一些操作，在上述代码中size方法就会触发这个操作。

```java
 public int size() {
         if (size == 0)
             return 0;
         expungeStaleEntries();
         return size;
     }
```

expungeStaleEntries方法代码如下。

```java
 private void expungeStaleEntries() {
         for (Object x; (x = queue.poll()) != null; ) {
             synchronized (queue) {
                 @SuppressWarnings("unchecked")
                     Entry<K,V> e = (Entry<K,V>) x;
                 int i = indexFor(e.hash, table.length);
  
                 Entry<K,V> prev = table[i];
                 Entry<K,V> p = prev;
                 while (p != null) {
                     Entry<K,V> next = p.next;
                     if (p == e) {
                         if (prev == e)
                             table[i] = next;
                         else
                             prev.next = next;
                         // Must not null out e.next;
                         // stale entries may be in use by a HashIterator
                         e.value = null; // Help GC
                         size--;
                         break;
                     }
                     prev = p;
                     p = next;
                 }
             }
         }
     }
```

这个方法，是从table中删除过时的条目，也就是弱引用被清除了之后，我们调用size方法来获取WeakHashMap的大小时，size方法会触发上面的方法，然后WeakHashMap去清除数据。



梳理上面代码的流程如下。

①：循环遍历引用队列（queue）， 如果发现某个对象被GC了，那么就开始处理。
②：如果被处理的这个节点是头节点，那么直接把该节点的下个节点放到头节点，然后帮助GC去除value的引用，接着把WeakHashMap的大小减1。
③：如果被处理的这个节点不是头结点，那么就需要把这个节点的上个节点中的next指针直接指向当前节点的下个节点。意思就是a->b->c，这个时候要移除b，那么就变成a->c。然后帮助GC去除value的引用，接着把WeakHashMap的大小减1。



## 方法

###  get(Object key) 方法

```Java
 public V get(Object key) {
     Object k = maskNull(key);
     int h = hash(k);
     Entry<K,V>[] tab = getTable();
     //获取桶在table中的index
     int index = indexFor(h, tab.length);
     //获取桶
     Entry<K,V> e = tab[index];
     //遍历桶中节点
     while (e != null) {
         if (e.hash == h && eq(k, e.get()))
             return e.value;
         e = e.next;
     }
     return null;
 }
```



###   containsKey(Object key)

```Java
 public boolean containsKey(Object key) {
         return getEntry(key) != null;
     }
  
     /**
      * Returns the entry associated with the specified key in this map.
      * Returns null if the map contains no mapping for this key.
      */
     Entry<K,V> getEntry(Object key) {
         Object k = maskNull(key); //因为此map容器允许Key为null的，只是存放进去的null都做了NULL_KEY处理，所以要检查一遍是否key为null
         int h = hash(k);
         Entry<K,V>[] tab = getTable();
         int index = indexFor(h, tab.length); //获取桶在table的index
         Entry<K,V> e = tab[index]; //该桶的第一个Entry结点
         while (e != null && !(e.hash == h && eq(k, e.get()))) //循环找到对应的Key
             e = e.next;
         return e;
     }
```



### put(K key, V value)

```Java
 /**
  * 将指定参数key和指定参数value插入map中，如果key已经存在，那就替换key对应的value
  *
  * @param key 指定key
  * @param value 指定value
  * @return 如果value被替换，则返回旧的value，否则返回null。当然，可能key对应的value就是null。
  */
 public V put(K key, V value) {
     Object k = maskNull(key);
     int h = hash(k); //获取该key的哈希地址
     Entry<K,V>[] tab = getTable();
     int i = indexFor(h, tab.length); //找到该哈希地址所在的桶的index
  
     for (Entry<K,V> e = tab[i]; e != null; e = e.next) { 
         if (h == e.hash && eq(k, e.get())) {
             V oldValue = e.value;
             if (value != oldValue)
                 e.value = value;
             return oldValue;
         }
     }
  
     modCount++;
     Entry<K,V> e = tab[i];
     tab[i] = new Entry<>(k, value, queue, h, e);
     if (++size >= threshold)
         resize(tab.length * 2);
     return null;
 }
```



###  putAll(Map<? extends K, ? extends V> m)

```Java
 public void putAll(Map<? extends K, ? extends V> m) {
         int numKeysToBeAdded = m.size();
         if (numKeysToBeAdded == 0)
             return;
  
         if (numKeysToBeAdded > threshold) { //如果要加入的map的原size大于阀值
             int targetCapacity = (int)(numKeysToBeAdded / loadFactor + 1);
             if (targetCapacity > MAXIMUM_CAPACITY)
                 targetCapacity = MAXIMUM_CAPACITY;
             int newCapacity = table.length;
             while (newCapacity < targetCapacity)
                 newCapacity <<= 1; //可以看到，newCapacity总是以两倍的大小在扩大
             if (newCapacity > table.length)
                 resize(newCapacity);
         }
  
         for (Map.Entry<? extends K, ? extends V> e : m.entrySet())
             put(e.getKey(), e.getValue());
     }
```



### remove(Object key)

该方法本质是删除某个单链表，即同一个桶中的内容都要被清除。

```java
 public V remove(Object key) {
         Object k = maskNull(key);
         int h = hash(k);
         Entry<K,V>[] tab = getTable();
         int i = indexFor(h, tab.length);
         Entry<K,V> prev = tab[i];
         Entry<K,V> e = prev;
  
         while (e != null) {
             Entry<K,V> next = e.next;
             if (h == e.hash && eq(k, e.get())) {
                 modCount++;
                 size--;
                 if (prev == e)
                     tab[i] = next;
                 else
                     prev.next = next;
                 return e.value;
             }
             prev = e;
             e = next;
         }
  
         return null;
     }
```



## 遍历方式

```java
 public class WeakHashMapIteratorTest {
  
     public static void main(String[] args) {
         int val = 0;
         String key = null;
         Integer value = null;
         Random r = new Random();
         WeakHashMap map = new WeakHashMap();
  
         for (int i=0; i<100; i++) {
             val = r.nextInt(100);
             key = String.valueOf(val);
             value = r.nextInt(5);
             map.put(key, value);
         }
         System.out.println("添加元素完成...");
  
         // 通过entrySet()遍历WeakHashMap的key-value
         iteratorHashMapByEntryset(map) ;
  
         // 通过keySet()遍历WeakHashMap的key-value
         iteratorHashMapByKeyset(map) ;
  
         // 单单遍历WeakHashMap的value
         iteratorHashMapJustValues(map);
     }
  
     /*
      * 通过entry set遍历WeakHashMap
      */
     private static void iteratorHashMapByEntryset(WeakHashMap map) {
         if (map == null)
             return ;
  
         String key = null;
         Integer integ = null;
  
         Iterator iter = map.entrySet().iterator();
  
         while(iter.hasNext()) {
             Map.Entry entry = (Map.Entry)iter.next();
  
             key = (String)entry.getKey();
             integ = (Integer)entry.getValue();
         }
         System.out.println("iteratorHashMapByEntryset--->>>size: " + map.size());
  
     }
  
     /*
      * 通过keyset来遍历WeakHashMap
      */
     private static void iteratorHashMapByKeyset(WeakHashMap map) {
         if (map == null)
             return ;
         String key = null;
         Integer integ = null;
  
         Iterator iter = map.keySet().iterator();
         while (iter.hasNext()) {
             key = (String)iter.next();
             integ = (Integer)map.get(key);
         }
  
         System.out.println("iteratorHashMapByKeyset--->>>size: " + map.size());
  
     }
      /*
      * 遍历WeakHashMap的values
      */
     private static void iteratorHashMapJustValues(WeakHashMap map) {
         if (map == null)
             return ;
  
         Collection c = map.values();
         Iterator iter= c.iterator();
  
         System.out.println("iteratorHashMapJustValues--->>>size: " + map.size());
         while (iter.hasNext()) {
             iter.next();
         }
  
     }
 }
```





