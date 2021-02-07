# ThreadLocal

ThreadLocal，简单翻译过来就是本地线程，但是直接这么翻译很难理解ThreadLocal的作用，如果换一种说法，可以称为线程本地存储。简单来说，就是ThreadLocal为共享变量在每个线程中都创建一个副本，每个线程可以访问自己内部的副本变量。这样做的好处是可以保证共享变量在多线程环境下访问的线程安全性

## ThreadLocal的使用

### 没有使用ThreadLocal时

通过一个简单的例子来演示一下ThreadLocal的作用，这段代码是定义了一个静态的成员变量`num`，然后通过构造5个线程对这个`num`做递增

```
public class ThreadLocalDemo {

    private static Integer num=0;

    public static void main(String[] args) {
        Thread[] threads=new Thread[5];
        for(int i=0;i<5;i++){
            threads[i]=new Thread(()->{
               num+=5;
               System.out.println(Thread.currentThread().getName()+" : "+num);
            },"Thread-"+i);
        }

        for(Thread thread:threads){
            thread.start();
        }
    }
}
```

运行结果

```
Thread-0 : 5
Thread-1 : 10
Thread-2 : 15
Thread-3 : 20
Thread-4 : 25
```

每个线程都会对这个成员变量做递增，如果线程的执行顺序不确定，那么意味着每个线程获得的结果也是不一样的。

### 使用了ThreadLocal以后

通过ThreadLocal对上面的代码做一个改动

```
public class ThreadLocalDemo {

    private static final ThreadLocal<Integer> local=new ThreadLocal<Integer>(){
        protected Integer initialValue(){
            return 0; //通过initialValue方法设置默认值
        }
    };

    public static void main(String[] args) {
        Thread[] threads=new Thread[5];
        for(int i=0;i<5;i++){
            threads[i]=new Thread(()->{
                int num=local.get().intValue();
                num+=5;
               System.out.println(Thread.currentThread().getName()+" : "+num);
            },"Thread-"+i);
        }

        for(Thread thread:threads){
            thread.start();
        }
    }
}
```

运行结果

```
Thread-0 : 5
Thread-4 : 5
Thread-2 : 5
Thread-1 : 5
Thread-3 : 5
```

从结果可以看到，每个线程的值都是5，意味着各个线程之间都是独立的变量副本，彼此不相互影响.

> ThreadLocal会给定一个初始值，也就是`initialValue()`方法，而每个线程都会从ThreadLocal中获得这个初始化的值的副本，这样可以使得每个线程都拥有一个副本拷贝

看到这里，估计有很多人都会和我一样有一些疑问

1. 每个线程的变量副本是怎么存储的?
2. ThreadLocal是如何实现多线程场景下的共享变量副本隔离?

带着疑问，来看一下ThreadLocal这个类的定义(默认情况下,JDK的源码都是基于1.8版本)

![ThreadLocal的全局图](https://segmentfault.com/img/bVbkDx0?w=505&h=215)

从ThreadLocal的方法定义来看,还是挺简单的。就几个方法

- get: 获取ThreadLocal中当前线程对应的线程局部变量
- set：设置当前线程的线程局部变量的值
- remove：将当前线程局部变量的值删除

另外，还有一个initialValue()方法，在前面的代码中有演示，作用是返回当前线程局部变量的初始值，这个方法是一个`protected`方法，主要是在构造ThreadLocal时用于设置默认的初始值

## set方法的实现

set方法是设置一个线程的局部变量的值，相当于当前线程通过set设置的局部变量的值，只对当前线程可见。

```
    public void set(T value) {
        Thread t = Thread.currentThread();//获取当前执行的线程
        ThreadLocalMap map = getMap(t); //获得当前线程的ThreadLocalMap实例
        if (map != null)//如果map不为空，说明当前线程已经有了一个ThreadLocalMap实例
            map.set(this, value);//直接将当前value设置到ThreadLocalMap中
        else
            createMap(t, value); //说明当前线程是第一次使用线程本地变量，构造map
    }
```

- `Thread.currentThread` 获取当前执行的线程
- `getMap(t)` ,根据当前线程得到当前线程的ThreadLocalMap对象，这个对象具体是做什么的?稍后分析
- 如果map不为空，说明当前线程已经构造过ThreadLocalMap，直接将值存储到map中
- 如果map为空，说明是第一次使用，调用`createMap`构造

### ThreadLocalMap是什么?

我们来分析一下这句话，`ThreadLocalMap map=getMap(t)`获得一个ThreadLocalMap对象，那这个对象是干嘛的呢?
其实不用分析，基本上也能猜测出来，Map是一个集合，集合用来存储数据，那么在ThreadLocal中，应该就是用来存储线程的局部变量的。`ThreadLocalMap`这个类很关键。

```
    ThreadLocalMap getMap(Thread t) {
        return t.threadLocals;
    }
```

t.threadLocals实际上就是访问Thread类中的ThreadLocalMap这个成员变量

```
public
class Thread implements Runnable {
 /* ThreadLocal values pertaining to this thread. This map is maintained
     * by the ThreadLocal class. */
    ThreadLocal.ThreadLocalMap threadLocals = null;
...
}
```

从上面的代码发现每一个线程都有自己单独的ThreadLocalMap实例，而对应这个线程的所有本地变量都会保存到这个map内

### ThreadLocalMap是在哪里构造?

在`set`方法中，有一行代码`createmap(t,value);`，这个方法就是用来构造ThreadLocalMap，从传入的参数来看，它的实现逻辑基本也能猜出出几分吧

```
    void createMap(Thread t, T firstValue) {
        t.threadLocals = new ThreadLocalMap(this, firstValue);
    }
```

`Thread t` 是通过`Thread.currentThread()`来获取的表示当前线程，然后直接通过`new ThreadLocalMap`将当前线程中的`threadLocals`做了初始化
ThreadLocalMap是一个静态内部类，内部定义了一个Entry对象用来真正存储数据

```Java
static class ThreadLocalMap {
        static class Entry extends WeakReference<ThreadLocal<?>> {
            /** The value associated with this ThreadLocal. */
            Object value;

            Entry(ThreadLocal<?> k, Object v) {
                super(k);
                value = v;
            }
        }
        ThreadLocalMap(ThreadLocal<?> firstKey, Object firstValue) {
            //构造一个Entry数组，并设置初始大小
            table = new Entry[INITIAL_CAPACITY];
            //计算Entry数据下标
            int i = firstKey.threadLocalHashCode & (INITIAL_CAPACITY - 1);
            //将`firstValue`存入到指定的table下标中
            table[i] = new Entry(firstKey, firstValue);
            size = 1;//设置节点长度为1
            setThreshold(INITIAL_CAPACITY); //设置扩容的阈值
        }
    //...省略部分代码
}
```

> 分析到这里，基本知道了ThreadLocalMap长啥样了，也知道它是如何构造的?那么我看到这里的时候仍然有疑问

- Entry继承了`WeakReference`,这个表示什么意思?
- 在构造ThreadLocalMap的时候`new ThreadLocalMap(this, firstValue);`,key其实是this，this表示当前对象的引用，在当前的案例中，this指的是`ThreadLocal local`。那么多个线程对应同一个ThreadLocal实例，怎么对每一个ThreadLocal对象做区分呢？

### 解惑WeakReference

weakReference表示弱引用，在Java中有四种引用类型，强引用、弱引用、软引用、虚引用。
使用弱引用的对象，不会阻止它所指向的对象被垃圾回收器回收。

在Java语言中, 当一个对象o被创建时, 它被放在Heap里. 当GC运行的时候, 如果发现没有任何引用指向o, o就会被回收以腾出内存空间. 也就是说, 一个对象被回收, 必须满足两个条件:

- 没有任何引用指向它
- GC被运行.

这段代码中，构造了两个对象a,b，a是对象DemoA的引用，b是对象DemoB的引用，对象DemoB同时还依赖对象DemoA，那么这个时候我们认为从对象DemoB是可以到达对象DemoA的。这种称为强可达(strongly reachable)

```
DemoA a=new DemoA();
DemoB b=new DemoB(a);
```

如果我们增加一行代码来将a对象的引用设置为null，当一个对象不再被其他对象引用的时候，是会被GC回收的，但是对于这个场景来说，即时是a=null，也不可能被回收，因为DemoB依赖DemoA，这个时候是可能造成内存泄漏的

```
DemoA a=new DemoA();
DemoB b=new DemoB(a);
a=null;
```

通过弱引用，有两个方法可以避免这样的问题

```
//方法1
DemoA a=new DemoA();
DemoB b=new DemoB(a);
a=null;
b=null;
//方法2
DemoA a=new DemoA();
WeakReference b=new WeakReference(a);
a=null;
```

对于方法2来说，DemoA只是被弱引用依赖，假设垃圾收集器在某个时间点决定一个对象是弱可达的(weakly reachable)（也就是说当前指向它的全都是弱引用），这时垃圾收集器会清除所有指向该对象的弱引用，然后把这个弱可达对象标记为可终结(finalizable)的，这样它随后就会被回收。

> 试想一下如果这里没有使用弱引用，意味着ThreadLocal的生命周期和线程是强绑定，只要线程没有销毁，那么ThreadLocal一直无法回收。而使用弱引用以后，当ThreadLocal被回收时，由于Entry的key是弱引用，不会影响ThreadLocal的回收防止内存泄漏，同时，在后续的源码分析中会看到，ThreadLocalMap本身的垃圾清理会用到这一个好处，方便对无效的Entry进行回收

### 解惑ThreadLocalMap以this作为key

在构造ThreadLocalMap时，使用this作为key来存储，那么对于同一个ThreadLocal对象，如果同一个Thread中存储了多个值，是如何来区分存储的呢？
答案就在`firstKey.threadLocalHashCode & (INITIAL_CAPACITY - 1)`

```
void createMap(Thread t, T firstValue) {
        t.threadLocals = new ThreadLocalMap(this, firstValue);
}

ThreadLocalMap(ThreadLocal<?> firstKey, Object firstValue) {
            table = new Entry[INITIAL_CAPACITY];
            int i = firstKey.threadLocalHashCode & (INITIAL_CAPACITY - 1);
            table[i] = new Entry(firstKey, firstValue);
            size = 1;
            setThreshold(INITIAL_CAPACITY);
}
```

关键点就在`threadLocalHashCode`，它相当于一个ThreadLocal的ID，实现的逻辑如下

```
private final int threadLocalHashCode = nextHashCode();
private static AtomicInteger nextHashCode =
        new AtomicInteger();
private static final int HASH_INCREMENT = 0x61c88647;

private static int nextHashCode() {
    return nextHashCode.getAndAdd(HASH_INCREMENT);
}
```

这里用到了一个非常完美的散列算法，可以简单理解为，对于同一个ThreadLocal下的多个线程来说，当任意线程调用set方法存入一个数据到Entry中的时候，其实会根据`threadLocalHashCode`生成一个唯一的id标识对应这个数据，存储在Entry数据下标中。

- `threadLocalHashCode`是通过nextHashCode.getAndAdd(HASH_INCREMENT)来实现的

`i*HASH_INCREMENT+HASH_INCREMENT`,每次新增一个元素(ThreadLocal)到Entry[],都会自增0x61c88647,目的为了让哈希码能均匀的分布在2的N次方的数组里

- Entry[i]= hashCode & (length-1)

### 魔数0x61c88647

从上面的分析可以看出，它是在上一个被构造出的ThreadLocal的threadLocalHashCode的基础上加上一个魔数0x61c88647。我们来做一个实验，看看这个散列算法的运算结果

```
    private static final int HASH_INCREMENT = 0x61c88647;
    public static void main(String[] args) {
        magicHash(16); //初始大小16
        magicHash(32); //扩容一倍
    }

    private static void magicHash(int size){
        int hashCode = 0;
        for(int i=0;i<size;i++){
            hashCode = i*HASH_INCREMENT+HASH_INCREMENT;
            System.out.print((hashCode & (size-1))+" ");
        }
        System.out.println();
    }
```

输出结果

```
7 14 5 12 3 10 1 8 15 6 13 4 11 2 9 0 
7 14 21 28 3 10 17 24 31 6 13 20 27 2 9 16 23 30 5 12 19 26 1 8 15 22 29 4 11 18 25 0 
```

根据运行结果，这个算法在长度为2的N次方的数组上，确实可以完美散列，没有任何冲突, 是不是很神奇。

> 魔数0x61c88647的选取和斐波那契散列有关，**0x61c88647**对应的十进制为1640531527。而斐波那契散列的乘数可以用`(long) ((1L << 31) * (Math.sqrt(5) - 1));` 如果把这个值给转为带符号的int，则会得到-1640531527。也就是说
> `(long) ((1L << 31) * (Math.sqrt(5) - 1));`得到的结果就是1640531527，也就是魔数**0x61c88647**

```
//(根号5-1)*2的31次方=(根号5-1)/2 *2的32次方=黄金分割数*2的32次方
long l1 = (long) ((1L << 31) * (Math.sqrt(5) - 1));
System.out.println("32位无符号整数: " + l1);
int i1 = (int) l1;
System.out.println("32位有符号整数:   " + i1);
```

> 总结，我们用0x61c88647作为魔数累加为每个ThreadLocal分配各自的ID也就是threadLocalHashCode再与2的幂取模，得到的结果分布很均匀。

### 图形分析

为了更直观的体现`set`方法的实现，通过一个图形表示如下

![set方法创造的ThreadLocalMap结构](https://segmentfault.com/img/bVbkBqa?w=1239&h=513)

## set剩余源码分析

前面分析了set方法第一次初始化ThreadLocalMap的过程，也对ThreadLocalMap的结构有了一个全面的了解。那么接下来看一下map不为空时的执行逻辑

```
private void set(ThreadLocal<?> key, Object value) {
            Entry[] tab = table;
            int len = tab.length;
            // 根据哈希码和数组长度求元素放置的位置，即数组下标
            int i = key.threadLocalHashCode & (len-1);
             //从i开始往后一直遍历到数组最后一个Entry(线性探索)
            for (Entry e = tab[i];
                 e != null;
                 e = tab[i = nextIndex(i, len)]) {
                ThreadLocal<?> k = e.get();
                 //如果key相等，覆盖value
                if (k == key) {
                    e.value = value;
                    return;
                }
                 //如果key为null,用新key、value覆盖，同时清理历史key=null的陈旧数据
                if (k == null) {
                    replaceStaleEntry(key, value, i);
                    return;
                }
            }

            tab[i] = new Entry(key, value);
            int sz = ++size;
             //如果超过阀值，就需要扩容了
            if (!cleanSomeSlots(i, sz) && sz >= threshold)
                rehash();
        }
```

主要逻辑

- 根据key的散列哈希计算Entry的数组下标
- 通过线性探索探测从i开始往后一直遍历到数组的最后一个Entry
- 如果map中的key和传入的key相等，表示该数据已经存在，直接覆盖
- 如果map中的key为空，则用新的key、value覆盖，并清理key=null的数据
- rehash扩容

### replaceStaleEntry

由于Entry的key为弱引用，如果key为空，说明ThreadLocal这个对象被GC回收了。
`replaceStaleEntry`的作用就是把陈旧的Entry进行替换

```
private void replaceStaleEntry(ThreadLocal<?> key, Object value,
                                       int staleSlot) {
            Entry[] tab = table;
            int len = tab.length;
            Entry e;

           //向前扫描，查找最前一个无效的slot
            int slotToExpunge = staleSlot;
            for (int i = prevIndex(staleSlot, len);
                 (e = tab[i]) != null;
                 i = prevIndex(i, len))
                if (e.get() == null)
                   //通过循环遍历，可以定位到最前面一个无效的slot
                    slotToExpunge = i; 

            //从i开始往后一直遍历到数组最后一个Entry（线性探索）
            for (int i = nextIndex(staleSlot, len);
                 (e = tab[i]) != null;
                 i = nextIndex(i, len)) {
                ThreadLocal<?> k = e.get();

                //找到匹配的key以后
                if (k == key) {
                    e.value = value;//更新对应slot的value值
                    //与无效的sloat进行交换
                    tab[i] = tab[staleSlot];
                    tab[staleSlot] = e;

                    //如果最早的一个无效的slot和当前的staleSlot相等，则从i作为清理的起点
                    if (slotToExpunge == staleSlot)
                        slotToExpunge = i;
                    //从slotToExpunge开始做一次连续的清理
                    cleanSomeSlots(expungeStaleEntry(slotToExpunge), len);
                    return;
                }

               
                //如果当前的slot已经无效，并且向前扫描过程中没有无效slot，则更新slotToExpunge为当前位置
                if (k == null && slotToExpunge == staleSlot)
                    slotToExpunge = i;
            }

            //如果key对应的value在entry中不存在，则直接放一个新的entry
            tab[staleSlot].value = null;
            tab[staleSlot] = new Entry(key, value);

           //如果有任何一个无效的slot，则做一次清理
            if (slotToExpunge != staleSlot)
                cleanSomeSlots(expungeStaleEntry(slotToExpunge), len);
        }
```

### cleanSomeSlots

这个函数有两处地方会被调用，用于清理无效的Entry

- 插入的时候可能会被调用
- 替换无效slot的时候可能会被调用

区别是前者传入的n为元素个数，后者为table的容量

```
private boolean cleanSomeSlots(int i, int n) {
            boolean removed = false;
            Entry[] tab = table;
            int len = tab.length;
            do {
                 // i在任何情况下自己都不会是一个无效slot，所以从下一个开始判断
                i = nextIndex(i, len);
                Entry e = tab[i];
                if (e != null && e.get() == null) {
                    n = len;// 扩大扫描控制因子
                    removed = true;
                    i = expungeStaleEntry(i); // 清理一个连续段
                }
            } while ( (n >>>= 1) != 0);
            return removed;
        }
```

### expungeStaleEntry

执行一次全量清理

```
private int expungeStaleEntry(int staleSlot) {
            Entry[] tab = table;
            int len = tab.length;

            // expunge entry at staleSlot
            tab[staleSlot].value = null;//删除value
            tab[staleSlot] = null;//删除entry
            size--; //map的size递减

            // Rehash until we encounter null
            Entry e;
            int i;
            for (i = nextIndex(staleSlot, len);// 遍历指定删除节点，所有后续节点
                 (e = tab[i]) != null;
                 i = nextIndex(i, len)) {
                ThreadLocal<?> k = e.get();
                if (k == null) {//key为null,执行删除操作
                    e.value = null;
                    tab[i] = null;
                    size--;
                } else {//key不为null,重新计算下标
                    int h = k.threadLocalHashCode & (len - 1);
                    if (h != i) {//如果不在同一个位置
                        tab[i] = null;//把老位置的entry置null(删除)

                        // 从h开始往后遍历，一直到找到空为止，插入
                        while (tab[h] != null)
                            h = nextIndex(h, len);
                        tab[h] = e;
                    }
                }
            }
            return i;
        }
```

## get操作

set的逻辑分析完成以后，get的源码分析就很简单了

```
public T get() {
        Thread t = Thread.currentThread();
        //从当前线程中获取ThreadLocalMap
        ThreadLocalMap map = getMap(t);
        if (map != null) {
            //查询当前ThreadLocal变量实例对应的Entry
            ThreadLocalMap.Entry e = map.getEntry(this);
            if (e != null) {//获取成功，直接返回
                @SuppressWarnings("unchecked")
                T result = (T)e.value;
                return result;
            }
        }
        //如果map为null,即还没有初始化，走初始化方法
        return setInitialValue();
    }
```

### setInitialValue

根据`initialValue()`的value初始化ThreadLocalMap

```
    private T setInitialValue() {
        T value = initialValue();//protected方法,用户可以重写
        Thread t = Thread.currentThread();
        ThreadLocalMap map = getMap(t);
        if (map != null)
            //如果map不为null,把初始化value设置进去
            map.set(this, value);
        else
            //如果map为null,则new一个map,并把初始化value设置进去
            createMap(t, value);
        return value;
    }
```

- 从当前线程中获取ThreadLocalMap，查询当前ThreadLocal变量实例对应的Entry，如果不为null,获取value,返回
- 如果map为null,即还没有初始化，走初始化方法

## remove方法

remove的方法比较简单，从Entry[]中删除指定的key就行

```
     public void remove() {
         ThreadLocalMap m = getMap(Thread.currentThread());
         if (m != null)
             m.remove(this);
     }

     private void remove(ThreadLocal<?> key) {
            Entry[] tab = table;
            int len = tab.length;
            int i = key.threadLocalHashCode & (len-1);
            for (Entry e = tab[i];
                 e != null;
                 e = tab[i = nextIndex(i, len)]) {
                if (e.get() == key) {
                    e.clear();//调用Entry的clear方法
                    expungeStaleEntry(i);//清除陈旧数据
                    return;
                }
            }
        }
```

## 应用场景

ThreadLocal的实际应用场景：

1. 比如在线程级别，维护session,维护用户登录信息userID（登陆时插入，多个地方获取）
2. 数据库的链接对象`Connection`，可以通过ThreadLocal来做隔离避免线程安全问题

## 问题

> ThreadLocal的内存泄漏

ThreadLocalMap中Entry的key使用的是ThreadLocal的弱引用，如果一个ThreadLocal没有外部强引用，当系统执行GC时，这个ThreadLocal势必会被回收，这样一来，ThreadLocalMap中就会出现一个key为null的Entry，而这个key=null的Entry是无法访问的，当这个线程一直没有结束的话，那么就会存在一条强引用链

![图片描述](https://segmentfault.com/img/bVbkDx1?w=604&h=314)

Thread Ref - > Thread -> ThreadLocalMap - > Entry -> value 永远无法回收而造成内存泄漏

> 其实我们从源码分析可以看到，ThreadLocalMap是做了防护措施的

- 首先从ThreadLocal的直接索引位置(通过ThreadLocal.threadLocalHashCode & (len-1)运算得到)获取Entry e，如果e不为null并且key相同则返回e
- 如果e为null或者key不一致则向下一个位置查询，如果下一个位置的key和当前需要查询的key相等，则返回对应的Entry，否则，如果key值为null，则擦除该位置的Entry，否则继续向下一个位置查询

在这个过程中遇到的key为null的Entry都会被擦除，那么Entry内的value也就没有强引用链，自然会被回收。仔细研究代码可以发现，set操作也有类似的思想，将key为null的这些Entry都删除，防止内存泄露。
但是这个设计一来与一个前提条件，就是调用get或者set方法，但是不是所有场景都会满足这个场景的，所以为了避免这类的问题，我们可以在合适的位置手动调用ThreadLocal的remove函数删除不需要的ThreadLocal，防止出现内存泄漏

**建议的使用方法是**

- 将ThreadLocal变量定义成private static的，这样的话ThreadLocal的生命周期就更长，由于一直存在ThreadLocal的强引用，所以ThreadLocal也就不会被回收，也就能保证任何时候都能根据ThreadLocal的弱引用访问到Entry的value值，然后remove它，防止内存泄露
- 每次使用完ThreadLocal，都调用它的remove()方法，清除数据。