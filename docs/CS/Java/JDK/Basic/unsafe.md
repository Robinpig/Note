# unsafe





### Direct Memory

[Direct Memory Management](/docs/CS/Java/JDK/Basic/Direct Memory.md)



### Memory Barrier

Fence like `volatile`

```java
    //Ensures lack of reordering of loads before the fence with loads or stores after the fence.
    public native void loadFence();

    //Ensures lack of reordering of stores before the fence with loads or stores after the fence.
    public native void storeFence();

    //Ensures lack of reordering of loads or stores before the fence with loads or stores after the fence.
    public native void fullFence();
```
OrderAccess

park



serial

getOffset 



putLong

### write object
performance
put > putOrder > putVolatile


allocateInstance not invoke constructor

## CAS



```cpp
// unsafe.cpp
UNSAFE_ENTRY(jboolean, Unsafe_CompareAndSetInt(JNIEnv *env, jobject unsafe, jobject obj, jlong offset, jint e, jint x)) {
  oop p = JNIHandles::resolve(obj);
  if (p == NULL) {
    volatile jint* addr = (volatile jint*)index_oop_from_field_offset_long(p, offset);
    return RawAccess<>::atomic_cmpxchg(x, addr, e) == e;
  } else {
    assert_field_offset_sane(p, offset);
    return HeapAccess<>::atomic_cmpxchg_at(x, p, (ptrdiff_t)offset, e) == e;
  }
} UNSAFE_END
```



```hpp
// atomic.hpp
// Handle cmpxchg for integral and enum types.
//
// All the involved types must be identical.
template<typename T>
struct Atomic::CmpxchgImpl<
  T, T, T,
  typename EnableIf<IsIntegral<T>::value || IsRegisteredEnum<T>::value>::type>
{
  T operator()(T exchange_value, T volatile* dest, T compare_value,
               atomic_memory_order order) const {
    // Forward to the platform handler for the size of T.
    return PlatformCmpxchg<sizeof(T)>()(exchange_value,
                                        dest,
                                        compare_value,
                                        order);
  }
};

// Handle cmpxchg for pointer types.
//
// The destination's type and the compare_value type must be the same,
// ignoring cv-qualifiers; we don't care about the cv-qualifiers of
// the compare_value.
//
// The exchange_value must be implicitly convertible to the
// destination's type; it must be type-correct to store the
// exchange_value in the destination.
template<typename T, typename D, typename U>
struct Atomic::CmpxchgImpl<
  T*, D*, U*,
  typename EnableIf<Atomic::IsPointerConvertible<T*, D*>::value &&
                    IsSame<typename RemoveCV<D>::type,
                           typename RemoveCV<U>::type>::value>::type>
{
  D* operator()(T* exchange_value, D* volatile* dest, U* compare_value,
               atomic_memory_order order) const {
    // Allow derived to base conversion, and adding cv-qualifiers.
    D* new_value = exchange_value;
    // Don't care what the CV qualifiers for compare_value are,
    // but we need to match D* when calling platform support.
    D* old_value = const_cast<D*>(compare_value);
    return PlatformCmpxchg<sizeof(D*)>()(new_value, dest, old_value, order);
  }
};

// Handle cmpxchg for types that have a translator.
//
// All the involved types must be identical.
//
// This translates the original call into a call on the decayed
// arguments, and returns the recovered result of that translated
// call.
template<typename T>
struct Atomic::CmpxchgImpl<
  T, T, T,
  typename EnableIf<PrimitiveConversions::Translate<T>::value>::type>
{
  T operator()(T exchange_value, T volatile* dest, T compare_value,
               atomic_memory_order order) const {
    typedef PrimitiveConversions::Translate<T> Translator;
    typedef typename Translator::Decayed Decayed;
    STATIC_ASSERT(sizeof(T) == sizeof(Decayed));
    return Translator::recover(
      cmpxchg(Translator::decay(exchange_value),
              reinterpret_cast<Decayed volatile*>(dest),
              Translator::decay(compare_value),
              order));
  }
};
```



Implement by os

```cpp
// atomic_linux_x86.hpp
inline T Atomic::PlatformCmpxchg<8>::operator()(T exchange_value,
                                                T volatile* dest,
                                                T compare_value,
                                                atomic_memory_order /* order */) const {
  STATIC_ASSERT(8 == sizeof(T));
  __asm__ __volatile__ ("lock cmpxchgq %1,(%3)"
                        : "=a" (exchange_value)
                        : "r" (exchange_value), "a" (compare_value), "r" (dest)
                        : "cc", "memory");
  return exchange_value;
}
```

monitor

Class