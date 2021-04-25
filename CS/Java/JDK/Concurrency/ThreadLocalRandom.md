# ThreadLocalRandom


![Random](https://github.com/Robinpig/Note/raw/master/images/JDK/Random.png)


## Random

`java.util.Random`

*An instance of this class is used to generate a stream of pseudorandom numbers. The class uses a **48-bit seed**, which is modified using a linear congruential formula. (See Donald Knuth, The Art of Computer Programming, Volume 2, Section 3.2.1.)*
*If **two instances of Random are created with the same seed, and the same sequence of method calls is made for each, they will generate and return identical sequences of numbers**.* 

*In order to guarantee this property, particular algorithms are specified for the class Random. Java implementations must use all the algorithms shown here for the class Random, for the sake of absolute portability of Java code. However, subclasses of class Random are permitted to use other algorithms, so long as they adhere to the general contracts for all the methods.*
*The algorithms implemented by class Random use a protected utility method that on each invocation can **supply up to 32 pseudorandomly generated bits**.*

*Many applications will find the method `Math.random` simpler to use.*

*Instances of `java.util.Random` are **threadsafe**. However, **the concurrent use of the same Random instance across threads may encounter contention and consequent poor performance**. Consider instead using **java.util.concurrent.ThreadLocalRandom** in multithreaded designs.*

*Instances of java.util.Random are **not cryptographically secure**. Consider instead using **java.security.SecureRandom** to get a cryptographically secure pseudo-random number generator for use by security-sensitive applications.*

```java
/**
 * The internal state associated with this pseudorandom number generator.
 * (The specs for the methods in this class describe the ongoing
 * computation of this value.)
 */
private final AtomicLong seed;

private static final long multiplier = 0x5DEECE66DL;
private static final long addend = 0xBL;
private static final long mask = (1L << 48) - 1;

private static final double DOUBLE_UNIT = 0x1.0p-53; // 1.0 / (1L << 53)

/**
 * Creates a new random number generator using a single long seed.
 * The seed is the initial value of the internal state of the pseudorandom
 * number generator which is maintained by method {@link #next}.
 */
public Random(long seed) {
    if (getClass() == Random.class)
        this.seed = new AtomicLong(initialScramble(seed));
    else {
        // subclass might have overridden setSeed
        this.seed = new AtomicLong();
        setSeed(seed);
    }
}

/**
 * Generates the next pseudorandom number. Subclasses should
 * override this, as this is used by all other methods.
 *
 * The general contract of next} is that it returns an
 *  int value and if the argument bits is between
 * 1 and 32 (inclusive), then that many low-order
 * bits of the returned value will be (approximately) independently
 * chosen bit values, each of which is (approximately) equally
 * likely to be 0 or 1. The method next} is
 * implemented by class Random} by atomically updating the seed to
 *  (seed * 0x5DEECE66DL + 0xBL) & ((1L << 48) - 1)
 * and returning
 *  (int)(seed >>> (48 - bits))
 */
protected int next(int bits) {
    long oldseed, nextseed;
    AtomicLong seed = this.seed;
    do {
        oldseed = seed.get();
        nextseed = (oldseed * multiplier + addend) & mask;
    } while (!seed.compareAndSet(oldseed, nextseed));
    return (int)(nextseed >>> (48 - bits));
}
```



## ThreadLocalRandom



*A **random number generator isolated to the current thread**. Like the global Random generator used by the Math class, a ThreadLocalRandom is initialized with an internally generated seed that may not otherwise be modified. When applicable, use of ThreadLocalRandom rather than shared Random objects in concurrent programs will typically encounter much less overhead and contention. **Use of ThreadLocalRandom is particularly appropriate when multiple tasks** (for example, each a **ForkJoinTask**) **use random numbers in parallel in thread pools**.*



### Get ThreadLocalRandom instance

Use `ThreadLocalRandom.current()` to get `static singleton`.

Call `localInit( )` when `Thread.threadLocalRandomProbe` is zero.

```java
/** Generates per-thread initialization/probe field */
private static final AtomicInteger probeGenerator = new AtomicInteger();

/** The common ThreadLocalRandom */
static final ThreadLocalRandom instance = new ThreadLocalRandom();

/**
 * The next seed for default constructors.
 */
private static final AtomicLong seeder
    = new AtomicLong(mix64(System.currentTimeMillis()) ^
                     mix64(System.nanoTime()));

/** Constructor used only for static singleton */
private ThreadLocalRandom() {
    initialized = true; // false during super() call
}

/**
 * Initialize Thread fields for the current thread.  Called only
 * when Thread.threadLocalRandomProbe is zero, indicating that a
 * thread local seed value needs to be generated. Note that even
 * though the initialization is purely thread-local, we need to
 * rely on (static) atomic generators to initialize the values.
 */
static final void localInit() {
    int p = probeGenerator.addAndGet(PROBE_INCREMENT);
    int probe = (p == 0) ? 1 : p; // skip 0
    long seed = mix64(seeder.getAndAdd(SEEDER_INCREMENT));
    Thread t = Thread.currentThread();
    U.putLong(t, SEED, seed);
    U.putInt(t, PROBE, probe);
}

/**
 * Returns the current thread's {@code ThreadLocalRandom}.
 */
public static ThreadLocalRandom current() {
    if (U.getInt(Thread.currentThread(), PROBE) == 0)
        localInit();
    return instance;
}
```



### Seed and Probe in Thread

*The following three initially uninitialized fields are exclusively managed by class `java.util.concurrent.ThreadLocalRandom`. These fields are used to build the high-performance PRNGs in the  concurrent code, and we can not risk accidental false sharing.  Hence, the fields are isolated with [**@Contended**]().*

```java
/** The current seed for a ThreadLocalRandom */
@jdk.internal.vm.annotation.Contended("tlr")
long threadLocalRandomSeed;

/** Probe hash value; nonzero if threadLocalRandomSeed initialized */
@jdk.internal.vm.annotation.Contended("tlr")
int threadLocalRandomProbe;

/** Secondary seed isolated from public ThreadLocalRandom sequence */
@jdk.internal.vm.annotation.Contended("tlr")
int threadLocalRandomSecondarySeed;
```



### Fields in ThreadLocalRandom

Use `jdk.internal.misc.Unsafe` get field in Thread.class.

```java
// Unsafe mechanics
private static final Unsafe U = Unsafe.getUnsafe();
private static final long SEED
    = U.objectFieldOffset(Thread.class, "threadLocalRandomSeed");
private static final long PROBE
    = U.objectFieldOffset(Thread.class, "threadLocalRandomProbe");
private static final long SECONDARY
    = U.objectFieldOffset(Thread.class, "threadLocalRandomSecondarySeed");
private static final long THREADLOCALS
    = U.objectFieldOffset(Thread.class, "threadLocals");
private static final long INHERITABLETHREADLOCALS
    = U.objectFieldOffset(Thread.class, "inheritableThreadLocals");
private static final long INHERITEDACCESSCONTROLCONTEXT
    = U.objectFieldOffset(Thread.class, "inheritedAccessControlContext");

/**
 * The seed increment.
 */
private static final long GAMMA = 0x9e3779b97f4a7c15L;

/**
 * The increment for generating probe values.
 */
private static final int PROBE_INCREMENT = 0x9e3779b9;

/**
 * The increment of seeder per new instance.
 */
private static final long SEEDER_INCREMENT = 0xbb67ae8584caa73bL;
```



### nextInt

```java
/**
 * Returns a pseudorandom {@code int} value.
 */
public int nextInt() {
    return mix32(nextSeed());
}

/**
 * Returns a pseudorandom {@code int} value between zero (inclusive)
 * and the specified bound (exclusive).
 */
public int nextInt(int bound) {
    if (bound <= 0)
        throw new IllegalArgumentException(BAD_BOUND);
    int r = mix32(nextSeed());
    int m = bound - 1;
    if ((bound & m) == 0) // power of two
        r &= m;
    else { // reject over-represented candidates
        for (int u = r >>> 1;
             u + m - (r = u % bound) < 0;
             u = mix32(nextSeed()) >>> 1)
            ;
    }
    return r;
}
```

**Mix**

```java
private static long mix64(long z) {
    z = (z ^ (z >>> 33)) * 0xff51afd7ed558ccdL;
    z = (z ^ (z >>> 33)) * 0xc4ceb9fe1a85ec53L;
    return z ^ (z >>> 33);
}

private static int mix32(long z) {
    z = (z ^ (z >>> 33)) * 0xff51afd7ed558ccdL;
    return (int)(((z ^ (z >>> 33)) * 0xc4ceb9fe1a85ec53L) >>> 32);
}
```



**nextSeed**

```java
final long nextSeed() {
    Thread t; long r; // read and update per-thread seed
    U.putLong(t = Thread.currentThread(), SEED,
              r = U.getLong(t, SEED) + GAMMA);
    return r;
}
```

### Secure

*Instances of ThreadLocalRandom are **not cryptographically secure**. Consider instead using java.security.SecureRandom in security-sensitive applications. Additionally, **default-constructed instances do not use a cryptographically random seed unless the system property java.util.secureRandomSeed is set to true**.*



```java
// at end of <clinit> to survive static initialization circularity
static {
    String sec = VM.getSavedProperty("java.util.secureRandomSeed");
    if (Boolean.parseBoolean(sec)) {
        byte[] seedBytes = java.security.SecureRandom.getSeed(8);
        long s = (long)seedBytes[0] & 0xffL;
        for (int i = 1; i < 8; ++i)
            s = (s << 8) | ((long)seedBytes[i] & 0xffL);
        seeder.set(s);
    }
}
```



## SecureRandom

*Constructs a secure random number generator (RNG) implementing the default random number algorithm.*
*This constructor traverses the list of registered security Providers, starting with the most preferred Provider. A new SecureRandom object encapsulating the SecureRandomSpi implementation from the first Provider that supports a SecureRandom (RNG) algorithm is returned. If none of the Providers support a RNG algorithm, then an implementation-specific default is returned.*
*Note that the list of registered providers may be retrieved via the **Security.getProviders()** method.*

```java
public SecureRandom() {
    /*
     * This call to our superclass constructor will result in a call
     * to our own {@code setSeed} method, which will return
     * immediately when it is passed zero.
     */
    super(0);
    getDefaultPRNG(false, null);
    this.threadSafe = getThreadSafe();
}

private boolean getThreadSafe() {
    if (provider == null || algorithm == null) {
        return false;
    } else {
        return Boolean.parseBoolean(provider.getProperty(
                "SecureRandom." + algorithm + " ThreadSafe", "false"));
    }
}
```

```java
private void getDefaultPRNG(boolean setSeed, byte[] seed) {
    Service prngService = null;
    String prngAlgorithm = null;
    for (Provider p : Providers.getProviderList().providers()) {
        // SUN provider uses the SunEntries.DEF_SECURE_RANDOM_ALGO
        // as the default SecureRandom algorithm; for other providers,
        // Provider.getDefaultSecureRandom() will use the 1st
        // registered SecureRandom algorithm
        if (p.getName().equals("SUN")) {
            prngAlgorithm = SunEntries.DEF_SECURE_RANDOM_ALGO;
            prngService = p.getService("SecureRandom", prngAlgorithm);
            break;
        } else {
            prngService = p.getDefaultSecureRandomService();
            if (prngService != null) {
                prngAlgorithm = prngService.getAlgorithm();
                break;
            }
        }
    }
    // per javadoc, if none of the Providers support a RNG algorithm,
    // then an implementation-specific default is returned.
    if (prngService == null) {
        prngAlgorithm = "SHA1PRNG";
        this.secureRandomSpi = new sun.security.provider.SecureRandom();
        this.provider = Providers.getSunProvider();
    } else {
        try {
            this.secureRandomSpi = (SecureRandomSpi)
                prngService.newInstance(null);
            this.provider = prngService.getProvider();
        } catch (NoSuchAlgorithmException nsae) {
            // should not happen
            throw new RuntimeException(nsae);
        }
    }
    if (setSeed) {
        this.secureRandomSpi.engineSetSeed(seed);
    }
    // JDK 1.1 based implementations subclass SecureRandom instead of
    // SecureRandomSpi. They will also go through this code path because
    // they must call a SecureRandom constructor as it is their superclass.
    // If we are dealing with such an implementation, do not set the
    // algorithm value as it would be inaccurate.
    if (getClass() == SecureRandom.class) {
        this.algorithm = prngAlgorithm;
    }
}
```

## Reference

1. [ThreadLocalRandom - 加多](https://ifeve.com/%e5%b9%b6%e5%8f%91%e5%8c%85%e4%b8%adthreadlocalrandom%e7%b1%bb%e5%8e%9f%e7%90%86%e5%89%96%e6%9e%90/)