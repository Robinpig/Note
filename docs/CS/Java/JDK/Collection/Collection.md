# Collection



![Collection](../images/Collection.png)



## Collection



```java
/**
 * The root interface in the <i>collection hierarchy</i>.  A collection
 * represents a group of objects, known as its <i>elements</i>.  Some
 * collections allow duplicate elements and others do not.  Some are ordered
 * and others unordered.  The JDK does not provide any <i>direct</i>
 * implementations of this interface: it provides implementations of more
 * specific subinterfaces like {@code Set} and {@code List}.  This interface
 * is typically used to pass collections around and manipulate them where
 * maximum generality is desired.
 *
 * <p><i>Bags</i> or <i>multisets</i> (unordered collections that may contain
 * duplicate elements) should implement this interface directly.
 *
 * <p>All general-purpose {@code Collection} implementation classes (which
 * typically implement {@code Collection} indirectly through one of its
 * subinterfaces) should provide two "standard" constructors: a void (no
 * arguments) constructor, which creates an empty collection, and a
 * constructor with a single argument of type {@code Collection}, which
 * creates a new collection with the same elements as its argument.  In
 * effect, the latter constructor allows the user to copy any collection,
 * producing an equivalent collection of the desired implementation type.
 * There is no way to enforce this convention (as interfaces cannot contain
 * constructors) but all of the general-purpose {@code Collection}
 * implementations in the Java platform libraries comply.
 *
 * <p>Certain methods are specified to be
 * <i>optional</i>. If a collection implementation doesn't implement a
 * particular operation, it should define the corresponding method to throw
 * {@code UnsupportedOperationException}. Such methods are marked "optional
 * operation" in method specifications of the collections interfaces.
 *
 * <p><a id="optional-restrictions"></a>Some collection implementations
 * have restrictions on the elements that they may contain.
 * For example, some implementations prohibit null elements,
 * and some have restrictions on the types of their elements.  Attempting to
 * add an ineligible element throws an unchecked exception, typically
 * {@code NullPointerException} or {@code ClassCastException}.  Attempting
 * to query the presence of an ineligible element may throw an exception,
 * or it may simply return false; some implementations will exhibit the former
 * behavior and some will exhibit the latter.  More generally, attempting an
 * operation on an ineligible element whose completion would not result in
 * the insertion of an ineligible element into the collection may throw an
 * exception or it may succeed, at the option of the implementation.
 * Such exceptions are marked as "optional" in the specification for this
 * interface.
 *
 * <p>It is up to each collection to determine its own synchronization
 * policy.  In the absence of a stronger guarantee by the
 * implementation, undefined behavior may result from the invocation
 * of any method on a collection that is being mutated by another
 * thread; this includes direct invocations, passing the collection to
 * a method that might perform invocations, and using an existing
 * iterator to examine the collection.
 *
 * <p>Many methods in Collections Framework interfaces are defined in
 * terms of the {@link Object#equals(Object) equals} method.  For example,
 * the specification for the {@link #contains(Object) contains(Object o)}
 * method says: "returns {@code true} if and only if this collection
 * contains at least one element {@code e} such that
 * {@code (o==null ? e==null : o.equals(e))}."  This specification should
 * <i>not</i> be construed to imply that invoking {@code Collection.contains}
 * with a non-null argument {@code o} will cause {@code o.equals(e)} to be
 * invoked for any element {@code e}.  Implementations are free to implement
 * optimizations whereby the {@code equals} invocation is avoided, for
 * example, by first comparing the hash codes of the two elements.  (The
 * {@link Object#hashCode()} specification guarantees that two objects with
 * unequal hash codes cannot be equal.)  More generally, implementations of
 * the various Collections Framework interfaces are free to take advantage of
 * the specified behavior of underlying {@link Object} methods wherever the
 * implementor deems it appropriate.
 *
 * <p>Some collection operations which perform recursive traversal of the
 * collection may fail with an exception for self-referential instances where
 * the collection directly or indirectly contains itself. This includes the
 * {@code clone()}, {@code equals()}, {@code hashCode()} and {@code toString()}
 * methods. Implementations may optionally handle the self-referential scenario,
 * however most current implementations do not do so.
 *
 * <h2><a id="view">View Collections</a></h2>
 *
 * <p>Most collections manage storage for elements they contain. By contrast, <i>view
 * collections</i> themselves do not store elements, but instead they rely on a
 * backing collection to store the actual elements. Operations that are not handled
 * by the view collection itself are delegated to the backing collection. Examples of
 * view collections include the wrapper collections returned by methods such as
 * {@link Collections#checkedCollection Collections.checkedCollection},
 * {@link Collections#synchronizedCollection Collections.synchronizedCollection}, and
 * {@link Collections#unmodifiableCollection Collections.unmodifiableCollection}.
 * Other examples of view collections include collections that provide a
 * different representation of the same elements, for example, as
 * provided by {@link List#subList List.subList},
 * {@link NavigableSet#subSet NavigableSet.subSet}, or
 * {@link Map#entrySet Map.entrySet}.
 * Any changes made to the backing collection are visible in the view collection.
 * Correspondingly, any changes made to the view collection &mdash; if changes
 * are permitted &mdash; are written through to the backing collection.
 * Although they technically aren't collections, instances of
 * {@link Iterator} and {@link ListIterator} can also allow modifications
 * to be written through to the backing collection, and in some cases,
 * modifications to the backing collection will be visible to the Iterator
 * during iteration.
 *
 * <h2><a id="unmodifiable">Unmodifiable Collections</a></h2>
 *
 * <p>Certain methods of this interface are considered "destructive" and are called
 * "mutator" methods in that they modify the group of objects contained within
 * the collection on which they operate. They can be specified to throw
 * {@code UnsupportedOperationException} if this collection implementation
 * does not support the operation. Such methods should (but are not required
 * to) throw an {@code UnsupportedOperationException} if the invocation would
 * have no effect on the collection. For example, consider a collection that
 * does not support the {@link #add add} operation. What will happen if the
 * {@link #addAll addAll} method is invoked on this collection, with an empty
 * collection as the argument? The addition of zero elements has no effect,
 * so it is permissible for this collection simply to do nothing and not to throw
 * an exception. However, it is recommended that such cases throw an exception
 * unconditionally, as throwing only in certain cases can lead to
 * programming errors.
 *
 * <p>An <i>unmodifiable collection</i> is a collection, all of whose
 * mutator methods (as defined above) are specified to throw
 * {@code UnsupportedOperationException}. Such a collection thus cannot be
 * modified by calling any methods on it. For a collection to be properly
 * unmodifiable, any view collections derived from it must also be unmodifiable.
 * For example, if a List is unmodifiable, the List returned by
 * {@link List#subList List.subList} is also unmodifiable.
 *
 * <p>An unmodifiable collection is not necessarily immutable. If the
 * contained elements are mutable, the entire collection is clearly
 * mutable, even though it might be unmodifiable. For example, consider
 * two unmodifiable lists containing mutable elements. The result of calling
 * {@code list1.equals(list2)} might differ from one call to the next if
 * the elements had been mutated, even though both lists are unmodifiable.
 * However, if an unmodifiable collection contains all immutable elements,
 * it can be considered effectively immutable.
 *
 * <h2><a id="unmodview">Unmodifiable View Collections</a></h2>
 *
 * <p>An <i>unmodifiable view collection</i> is a collection that is unmodifiable
 * and that is also a view onto a backing collection. Its mutator methods throw
 * {@code UnsupportedOperationException}, as described above, while
 * reading and querying methods are delegated to the backing collection.
 * The effect is to provide read-only access to the backing collection.
 * This is useful for a component to provide users with read access to
 * an internal collection, while preventing them from modifying such
 * collections unexpectedly. Examples of unmodifiable view collections
 * are those returned by the
 * {@link Collections#unmodifiableCollection Collections.unmodifiableCollection},
 * {@link Collections#unmodifiableList Collections.unmodifiableList}, and
 * related methods.
 *
 * <p>Note that changes to the backing collection might still be possible,
 * and if they occur, they are visible through the unmodifiable view. Thus,
 * an unmodifiable view collection is not necessarily immutable. However,
 * if the backing collection of an unmodifiable view is effectively immutable,
 * or if the only reference to the backing collection is through an
 * unmodifiable view, the view can be considered effectively immutable.
 *
 * <h2><a id="serializable">Serializability of Collections</a></h2>
 *
 * <p>Serializability of collections is optional. As such, none of the collections
 * interfaces are declared to implement the {@link java.io.Serializable} interface.
 * However, serializability is regarded as being generally useful, so most collection
 * implementations are serializable.
 *
 * <p>The collection implementations that are public classes (such as {@code ArrayList}
 * or {@code HashMap}) are declared to implement the {@code Serializable} interface if they
 * are in fact serializable. Some collections implementations are not public classes,
 * such as the <a href="#unmodifiable">unmodifiable collections.</a> In such cases, the
 * serializability of such collections is described in the specification of the method
 * that creates them, or in some other suitable place. In cases where the serializability
 * of a collection is not specified, there is no guarantee about the serializability of such
 * collections. In particular, many <a href="#view">view collections</a> are not serializable.
 *
 * <p>A collection implementation that implements the {@code Serializable} interface cannot
 * be guaranteed to be serializable. The reason is that in general, collections
 * contain elements of other types, and it is not possible to determine statically
 * whether instances of some element type are actually serializable. For example, consider
 * a serializable {@code Collection<E>}, where {@code E} does not implement the
 * {@code Serializable} interface. The collection may be serializable, if it contains only
 * elements of some serializable subtype of {@code E}, or if it is empty. Collections are
 * thus said to be <i>conditionally serializable,</i> as the serializability of the collection
 * as a whole depends on whether the collection itself is serializable and on whether all
 * contained elements are also serializable.
 *
 * <p>An additional case occurs with instances of {@link SortedSet} and {@link SortedMap}.
 * These collections can be created with a {@link Comparator} that imposes an ordering on
 * the set elements or map keys. Such a collection is serializable only if the provided
 * {@code Comparator} is also serializable.
 *
 * <p>This interface is a member of the
 * <a href="{@docRoot}/java.base/java/util/package-summary.html#CollectionsFramework">
 * Java Collections Framework</a>.
 *
 * @implSpec
 * The default method implementations (inherited or otherwise) do not apply any
 * synchronization protocol.  If a {@code Collection} implementation has a
 * specific synchronization protocol, then it must override default
 * implementations to apply that protocol.
 *
 * @param <E> the type of elements in this collection
 * @see     Set
 * @see     List
 * @see     Map
 * @see     SortedSet
 * @see     SortedMap
 * @see     HashSet
 * @see     TreeSet
 * @see     ArrayList
 * @see     LinkedList
 * @see     Vector
 * @see     Collections
 * @see     Arrays
 * @see     AbstractCollection
 * @since 1.2
 */

public interface Collection<E> extends Iterable<E> {
    // Query Operations

    /**
     * Returns the number of elements in this collection.  If this collection
     * contains more than {@code Integer.MAX_VALUE} elements, returns
     * {@code Integer.MAX_VALUE}.
     *
     * @return the number of elements in this collection
     */
    int size();

    /**
     * Returns {@code true} if this collection contains no elements.
     *
     * @return {@code true} if this collection contains no elements
     */
    boolean isEmpty();

    /**
     * Returns {@code true} if this collection contains the specified element.
     * More formally, returns {@code true} if and only if this collection
     * contains at least one element {@code e} such that
     * {@code Objects.equals(o, e)}.
     *
     * @param o element whose presence in this collection is to be tested
     * @return {@code true} if this collection contains the specified
     *         element
     * @throws ClassCastException if the type of the specified element
     *         is incompatible with this collection
     *         (<a href="{@docRoot}/java.base/java/util/Collection.html#optional-restrictions">optional</a>)
     * @throws NullPointerException if the specified element is null and this
     *         collection does not permit null elements
     *         (<a href="{@docRoot}/java.base/java/util/Collection.html#optional-restrictions">optional</a>)
     */
    boolean contains(Object o);

    /**
     * Returns an iterator over the elements in this collection.  There are no
     * guarantees concerning the order in which the elements are returned
     * (unless this collection is an instance of some class that provides a
     * guarantee).
     *
     * @return an {@code Iterator} over the elements in this collection
     */
    Iterator<E> iterator();

    /**
     * Returns an array containing all of the elements in this collection.
     * If this collection makes any guarantees as to what order its elements
     * are returned by its iterator, this method must return the elements in
     * the same order. The returned array's {@linkplain Class#getComponentType
     * runtime component type} is {@code Object}.
     *
     * <p>The returned array will be "safe" in that no references to it are
     * maintained by this collection.  (In other words, this method must
     * allocate a new array even if this collection is backed by an array).
     * The caller is thus free to modify the returned array.
     *
     * @apiNote
     * This method acts as a bridge between array-based and collection-based APIs.
     * It returns an array whose runtime type is {@code Object[]}.
     * Use {@link #toArray(Object[]) toArray(T[])} to reuse an existing
     * array, or use {@link #toArray(IntFunction)} to control the runtime type
     * of the array.
     *
     * @return an array, whose {@linkplain Class#getComponentType runtime component
     * type} is {@code Object}, containing all of the elements in this collection
     */
    Object[] toArray();

    /**
     * Returns an array containing all of the elements in this collection;
     * the runtime type of the returned array is that of the specified array.
     * If the collection fits in the specified array, it is returned therein.
     * Otherwise, a new array is allocated with the runtime type of the
     * specified array and the size of this collection.
     *
     * <p>If this collection fits in the specified array with room to spare
     * (i.e., the array has more elements than this collection), the element
     * in the array immediately following the end of the collection is set to
     * {@code null}.  (This is useful in determining the length of this
     * collection <i>only</i> if the caller knows that this collection does
     * not contain any {@code null} elements.)
     *
     * <p>If this collection makes any guarantees as to what order its elements
     * are returned by its iterator, this method must return the elements in
     * the same order.
     *
     * @apiNote
     * This method acts as a bridge between array-based and collection-based APIs.
     * It allows an existing array to be reused under certain circumstances.
     * Use {@link #toArray()} to create an array whose runtime type is {@code Object[]},
     * or use {@link #toArray(IntFunction)} to control the runtime type of
     * the array.
     *
     * <p>Suppose {@code x} is a collection known to contain only strings.
     * The following code can be used to dump the collection into a previously
     * allocated {@code String} array:
     *
     * <pre>
     *     String[] y = new String[SIZE];
     *     ...
     *     y = x.toArray(y);</pre>
     *
     * <p>The return value is reassigned to the variable {@code y}, because a
     * new array will be allocated and returned if the collection {@code x} has
     * too many elements to fit into the existing array {@code y}.
     *
     * <p>Note that {@code toArray(new Object[0])} is identical in function to
     * {@code toArray()}.
     *
     * @param <T> the component type of the array to contain the collection
     * @param a the array into which the elements of this collection are to be
     *        stored, if it is big enough; otherwise, a new array of the same
     *        runtime type is allocated for this purpose.
     * @return an array containing all of the elements in this collection
     * @throws ArrayStoreException if the runtime type of any element in this
     *         collection is not assignable to the {@linkplain Class#getComponentType
     *         runtime component type} of the specified array
     * @throws NullPointerException if the specified array is null
     */
    <T> T[] toArray(T[] a);

    /**
     * Returns an array containing all of the elements in this collection,
     * using the provided {@code generator} function to allocate the returned array.
     *
     * <p>If this collection makes any guarantees as to what order its elements
     * are returned by its iterator, this method must return the elements in
     * the same order.
     *
     * @apiNote
     * This method acts as a bridge between array-based and collection-based APIs.
     * It allows creation of an array of a particular runtime type. Use
     * {@link #toArray()} to create an array whose runtime type is {@code Object[]},
     * or use {@link #toArray(Object[]) toArray(T[])} to reuse an existing array.
     *
     * <p>Suppose {@code x} is a collection known to contain only strings.
     * The following code can be used to dump the collection into a newly
     * allocated array of {@code String}:
     *
     * <pre>
     *     String[] y = x.toArray(String[]::new);</pre>
     *
     * @implSpec
     * The default implementation calls the generator function with zero
     * and then passes the resulting array to {@link #toArray(Object[]) toArray(T[])}.
     *
     * @param <T> the component type of the array to contain the collection
     * @param generator a function which produces a new array of the desired
     *                  type and the provided length
     * @return an array containing all of the elements in this collection
     * @throws ArrayStoreException if the runtime type of any element in this
     *         collection is not assignable to the {@linkplain Class#getComponentType
     *         runtime component type} of the generated array
     * @throws NullPointerException if the generator function is null
     * @since 11
     */
    default <T> T[] toArray(IntFunction<T[]> generator) {
        return toArray(generator.apply(0));
    }

    // Modification Operations

    /**
     * Ensures that this collection contains the specified element (optional
     * operation).  Returns {@code true} if this collection changed as a
     * result of the call.  (Returns {@code false} if this collection does
     * not permit duplicates and already contains the specified element.)<p>
     *
     * Collections that support this operation may place limitations on what
     * elements may be added to this collection.  In particular, some
     * collections will refuse to add {@code null} elements, and others will
     * impose restrictions on the type of elements that may be added.
     * Collection classes should clearly specify in their documentation any
     * restrictions on what elements may be added.<p>
     *
     * If a collection refuses to add a particular element for any reason
     * other than that it already contains the element, it <i>must</i> throw
     * an exception (rather than returning {@code false}).  This preserves
     * the invariant that a collection always contains the specified element
     * after this call returns.
     *
     * @param e element whose presence in this collection is to be ensured
     * @return {@code true} if this collection changed as a result of the
     *         call
     * @throws UnsupportedOperationException if the {@code add} operation
     *         is not supported by this collection
     * @throws ClassCastException if the class of the specified element
     *         prevents it from being added to this collection
     * @throws NullPointerException if the specified element is null and this
     *         collection does not permit null elements
     * @throws IllegalArgumentException if some property of the element
     *         prevents it from being added to this collection
     * @throws IllegalStateException if the element cannot be added at this
     *         time due to insertion restrictions
     */
    boolean add(E e);

    /**
     * Removes a single instance of the specified element from this
     * collection, if it is present (optional operation).  More formally,
     * removes an element {@code e} such that
     * {@code Objects.equals(o, e)}, if
     * this collection contains one or more such elements.  Returns
     * {@code true} if this collection contained the specified element (or
     * equivalently, if this collection changed as a result of the call).
     *
     * @param o element to be removed from this collection, if present
     * @return {@code true} if an element was removed as a result of this call
     * @throws ClassCastException if the type of the specified element
     *         is incompatible with this collection
     *         (<a href="{@docRoot}/java.base/java/util/Collection.html#optional-restrictions">optional</a>)
     * @throws NullPointerException if the specified element is null and this
     *         collection does not permit null elements
     *         (<a href="{@docRoot}/java.base/java/util/Collection.html#optional-restrictions">optional</a>)
     * @throws UnsupportedOperationException if the {@code remove} operation
     *         is not supported by this collection
     */
    boolean remove(Object o);


    // Bulk Operations

    /**
     * Returns {@code true} if this collection contains all of the elements
     * in the specified collection.
     *
     * @param  c collection to be checked for containment in this collection
     * @return {@code true} if this collection contains all of the elements
     *         in the specified collection
     * @throws ClassCastException if the types of one or more elements
     *         in the specified collection are incompatible with this
     *         collection
     *         (<a href="{@docRoot}/java.base/java/util/Collection.html#optional-restrictions">optional</a>)
     * @throws NullPointerException if the specified collection contains one
     *         or more null elements and this collection does not permit null
     *         elements
     *         (<a href="{@docRoot}/java.base/java/util/Collection.html#optional-restrictions">optional</a>),
     *         or if the specified collection is null.
     * @see    #contains(Object)
     */
    boolean containsAll(Collection<?> c);

    /**
     * Adds all of the elements in the specified collection to this collection
     * (optional operation).  The behavior of this operation is undefined if
     * the specified collection is modified while the operation is in progress.
     * (This implies that the behavior of this call is undefined if the
     * specified collection is this collection, and this collection is
     * nonempty.)
     *
     * @param c collection containing elements to be added to this collection
     * @return {@code true} if this collection changed as a result of the call
     * @throws UnsupportedOperationException if the {@code addAll} operation
     *         is not supported by this collection
     * @throws ClassCastException if the class of an element of the specified
     *         collection prevents it from being added to this collection
     * @throws NullPointerException if the specified collection contains a
     *         null element and this collection does not permit null elements,
     *         or if the specified collection is null
     * @throws IllegalArgumentException if some property of an element of the
     *         specified collection prevents it from being added to this
     *         collection
     * @throws IllegalStateException if not all the elements can be added at
     *         this time due to insertion restrictions
     * @see #add(Object)
     */
    boolean addAll(Collection<? extends E> c);

    /**
     * Removes all of this collection's elements that are also contained in the
     * specified collection (optional operation).  After this call returns,
     * this collection will contain no elements in common with the specified
     * collection.
     *
     * @param c collection containing elements to be removed from this collection
     * @return {@code true} if this collection changed as a result of the
     *         call
     * @throws UnsupportedOperationException if the {@code removeAll} method
     *         is not supported by this collection
     * @throws ClassCastException if the types of one or more elements
     *         in this collection are incompatible with the specified
     *         collection
     *         (<a href="{@docRoot}/java.base/java/util/Collection.html#optional-restrictions">optional</a>)
     * @throws NullPointerException if this collection contains one or more
     *         null elements and the specified collection does not support
     *         null elements
     *         (<a href="{@docRoot}/java.base/java/util/Collection.html#optional-restrictions">optional</a>),
     *         or if the specified collection is null
     * @see #remove(Object)
     * @see #contains(Object)
     */
    boolean removeAll(Collection<?> c);

    /**
     * Removes all of the elements of this collection that satisfy the given
     * predicate.  Errors or runtime exceptions thrown during iteration or by
     * the predicate are relayed to the caller.
     *
     * @implSpec
     * The default implementation traverses all elements of the collection using
     * its {@link #iterator}.  Each matching element is removed using
     * {@link Iterator#remove()}.  If the collection's iterator does not
     * support removal then an {@code UnsupportedOperationException} will be
     * thrown on the first matching element.
     *
     * @param filter a predicate which returns {@code true} for elements to be
     *        removed
     * @return {@code true} if any elements were removed
     * @throws NullPointerException if the specified filter is null
     * @throws UnsupportedOperationException if elements cannot be removed
     *         from this collection.  Implementations may throw this exception if a
     *         matching element cannot be removed or if, in general, removal is not
     *         supported.
     * @since 1.8
     */
    default boolean removeIf(Predicate<? super E> filter) {
        Objects.requireNonNull(filter);
        boolean removed = false;
        final Iterator<E> each = iterator();
        while (each.hasNext()) {
            if (filter.test(each.next())) {
                each.remove();
                removed = true;
            }
        }
        return removed;
    }

    /**
     * Retains only the elements in this collection that are contained in the
     * specified collection (optional operation).  In other words, removes from
     * this collection all of its elements that are not contained in the
     * specified collection.
     */
    boolean retainAll(Collection<?> c);

    /**
     * Removes all of the elements from this collection (optional operation).
     * The collection will be empty after this method returns.
     *
     * @throws UnsupportedOperationException if the {@code clear} operation
     *         is not supported by this collection
     */
    void clear();


    // Comparison and hashing

    /**
     * Compares the specified object with this collection for equality. <p>
     *
     * While the {@code Collection} interface adds no stipulations to the
     * general contract for the {@code Object.equals}, programmers who
     * implement the {@code Collection} interface "directly" (in other words,
     * create a class that is a {@code Collection} but is not a {@code Set}
     * or a {@code List}) must exercise care if they choose to override the
     * {@code Object.equals}.  It is not necessary to do so, and the simplest
     * course of action is to rely on {@code Object}'s implementation, but
     * the implementor may wish to implement a "value comparison" in place of
     * the default "reference comparison."  (The {@code List} and
     * {@code Set} interfaces mandate such value comparisons.)<p>
     *
     * The general contract for the {@code Object.equals} method states that
     * equals must be symmetric (in other words, {@code a.equals(b)} if and
     * only if {@code b.equals(a)}).  The contracts for {@code List.equals}
     * and {@code Set.equals} state that lists are only equal to other lists,
     * and sets to other sets.  Thus, a custom {@code equals} method for a
     * collection class that implements neither the {@code List} nor
     * {@code Set} interface must return {@code false} when this collection
     * is compared to any list or set.  (By the same logic, it is not possible
     * to write a class that correctly implements both the {@code Set} and
     * {@code List} interfaces.)
     */
    boolean equals(Object o);

    /**
     * Returns the hash code value for this collection.  While the
     * {@code Collection} interface adds no stipulations to the general
     * contract for the {@code Object.hashCode} method, programmers should
     * take note that any class that overrides the {@code Object.equals}
     * method must also override the {@code Object.hashCode} method in order
     * to satisfy the general contract for the {@code Object.hashCode} method.
     * In particular, {@code c1.equals(c2)} implies that
     * {@code c1.hashCode()==c2.hashCode()}.
     */
    int hashCode();

```



Since 1.8 add Stream API

```java
    /**
     * Creates a {@link Spliterator} over the elements in this collection.
     *
     * Implementations should document characteristic values reported by the
     * spliterator.  Such characteristic values are not required to be reported
     * if the spliterator reports {@link Spliterator#SIZED} and this collection
     * contains no elements.
     *
     * <p>The default implementation should be overridden by subclasses that
     * can return a more efficient spliterator.  In order to
     * preserve expected laziness behavior for the {@link #stream()} and
     * {@link #parallelStream()} methods, spliterators should either have the
     * characteristic of {@code IMMUTABLE} or {@code CONCURRENT}, or be
     * <em><a href="Spliterator.html#binding">late-binding</a></em>.
     * If none of these is practical, the overriding class should describe the
     * spliterator's documented policy of binding and structural interference,
     * and should override the {@link #stream()} and {@link #parallelStream()}
     * methods to create streams using a {@code Supplier} of the spliterator,
     * as in:
     * <pre>{@code
     *     Stream<E> s = StreamSupport.stream(() -> spliterator(), spliteratorCharacteristics)
     * }</pre>
     * <p>These requirements ensure that streams produced by the
     * {@link #stream()} and {@link #parallelStream()} methods will reflect the
     * contents of the collection as of initiation of the terminal stream
     * operation.
     *
     * @implSpec
     * The default implementation creates a
     * <em><a href="Spliterator.html#binding">late-binding</a></em> spliterator
     * from the collection's {@code Iterator}.  The spliterator inherits the
     * <em>fail-fast</em> properties of the collection's iterator.
     * <p>
     * The created {@code Spliterator} reports {@link Spliterator#SIZED}.
     *
     * @implNote
     * The created {@code Spliterator} additionally reports
     * {@link Spliterator#SUBSIZED}.
     *
     * <p>If a spliterator covers no elements then the reporting of additional
     * characteristic values, beyond that of {@code SIZED} and {@code SUBSIZED},
     * does not aid clients to control, specialize or simplify computation.
     * However, this does enable shared use of an immutable and empty
     * spliterator instance (see {@link Spliterators#emptySpliterator()}) for
     * empty collections, and enables clients to determine if such a spliterator
     * covers no elements.
     *
     * @return a {@code Spliterator} over the elements in this collection
     * @since 1.8
     */
    @Override
    default Spliterator<E> spliterator() {
        return Spliterators.spliterator(this, 0);
    }

    /**
     * Returns a sequential {@code Stream} with this collection as its source.
     *
     * <p>This method should be overridden when the {@link #spliterator()}
     * method cannot return a spliterator that is {@code IMMUTABLE},
     * {@code CONCURRENT}, or <em>late-binding</em>. (See {@link #spliterator()}
     * for details.)
     *
     * @implSpec
     * The default implementation creates a sequential {@code Stream} from the
     * collection's {@code Spliterator}.
     *
     * @return a sequential {@code Stream} over the elements in this collection
     * @since 1.8
     */
    default Stream<E> stream() {
        return StreamSupport.stream(spliterator(), false);
    }

    /**
     * Returns a possibly parallel {@code Stream} with this collection as its
     * source.  It is allowable for this method to return a sequential stream.
     *
     * <p>This method should be overridden when the {@link #spliterator()}
     * method cannot return a spliterator that is {@code IMMUTABLE},
     * {@code CONCURRENT}, or <em>late-binding</em>. (See {@link #spliterator()}
     * for details.)
     *
     * @implSpec
     * The default implementation creates a parallel {@code Stream} from the
     * collection's {@code Spliterator}.
     *
     * @return a possibly parallel {@code Stream} over the elements in this
     * collection
     * @since 1.8
     */
    default Stream<E> parallelStream() {
        return StreamSupport.stream(spliterator(), true);
    }
}
```

Allocate  memory when first element added.





## Concurrent Modify

### Fail-Fast

#### ConcurrentModificationException

*This exception may be thrown by methods that have detected concurrent modification of an object when such modification is not permissible.*

1. *For example, **it is not generally permissible for one thread to modify a Collection while another thread is iterating over it**. In general, the results of the iteration are undefined under these circumstances. Some Iterator implementations (including those of all the general purpose collection implementations provided by the JRE) may choose to throw this exception if this behavior is detected. Iterators that do this are known as fail-fast iterators, as they fail quickly and cleanly, rather that risking arbitrary, non-deterministic behavior at an undetermined time in the future.*
2.  If **a single thread issues a sequence of method invocations that violates the contract of an object, the object may throw this exception**. For example, if a thread modifies a collection directly while it is iterating over the collection with a fail-fast iterator, the iterator will throw this exception.*

*Note that fail-fast behavior cannot be guaranteed as it is, generally speaking, impossible to make any hard guarantees in the presence of unsynchronized concurrent modification. Fail-fast operations throw ConcurrentModificationException on a best-effort basis. Therefore, it would be wrong to write a program that depended on this exception for its correctness: **ConcurrentModificationException should be used only to detect bugs**.*



### Fail-Safe

For example CopyOnWriteArrayList.


## Arrays



### asList

Returns a **fixed-size** list( **java.util.Arrays$ArrayList** ) backed by the specified array. (Changes to the returned list "write through" to the array.) This method acts as bridge between array-based and collection-based APIs, in combination with Collection.toArray. The returned list is serializable and implements RandomAccess.
This method also provides a convenient way to create a fixed-size list initialized to contain several elements:
           List<String> stooges = Arrays.asList("Larry", "Moe", "Curly");

```java
public static <T> List<T> asList(T... a) {
    return new ArrayList<>(a);
}
```

- When the parameter is primitiveType array, the List only has one element of this array.
- The  java.util.Arrays$ArrayList can't use remove method.



## Iterable



```java
/**
 * Implementing this interface allows an object to be the target of the enhanced
 * {@code for} statement (sometimes called the "for-each loop" statement).
 *
 * @param <T> the type of elements returned by the iterator
 *
 * @since 1.5
 * @jls 14.14.2 The enhanced {@code for} statement
 */
public interface Iterable<T> {
    /**
     * Returns an iterator over elements of type {@code T}.
     *
     * @return an Iterator.
     */
    Iterator<T> iterator();

    /**
     * Performs the given action for each element of the {@code Iterable}
     * until all elements have been processed or the action throws an
     * exception.  Actions are performed in the order of iteration, if that
     * order is specified.  Exceptions thrown by the action are relayed to the
     * caller.
     * <p>
     * The behavior of this method is unspecified if the action performs
     * side-effects that modify the underlying source of elements, unless an
     * overriding class has specified a concurrent modification policy.
     *
     * @implSpec
     * <p>The default implementation behaves as if:
     * <pre>{@code
     *     for (T t : this)
     *         action.accept(t);
     * }</pre>
     *
     * @param action The action to be performed for each element
     * @throws NullPointerException if the specified action is null
     * @since 1.8
     */
    default void forEach(Consumer<? super T> action) {
        Objects.requireNonNull(action);
        for (T t : this) {
            action.accept(t);
        }
    }

    /**
     * Creates a {@link Spliterator} over the elements described by this
     * {@code Iterable}.
     *
     * @implSpec
     * The default implementation creates an
     * <em><a href="../util/Spliterator.html#binding">early-binding</a></em>
     * spliterator from the iterable's {@code Iterator}.  The spliterator
     * inherits the <em>fail-fast</em> properties of the iterable's iterator.
     *
     * @implNote
     * The default implementation should usually be overridden.  The
     * spliterator returned by the default implementation has poor splitting
     * capabilities, is unsized, and does not report any spliterator
     * characteristics. Implementing classes can nearly always provide a
     * better implementation.
     *
     * @return a {@code Spliterator} over the elements described by this
     * {@code Iterable}.
     * @since 1.8
     */
    default Spliterator<T> spliterator() {
        return Spliterators.spliteratorUnknownSize(iterator(), 0);
    }
}
```



### Iterator

```java
/**
 * An iterator over a collection.  {@code Iterator} takes the place of
 * {@link Enumeration} in the Java Collections Framework.  Iterators
 * differ from enumerations in two ways:
 *
 * <ul>
 *      <li> Iterators allow the caller to remove elements from the
 *           underlying collection during the iteration with well-defined
 *           semantics.
 *      <li> Method names have been improved.
 * </ul>
 *
 * <p>This interface is a member of the
 * <a href="{@docRoot}/java.base/java/util/package-summary.html#CollectionsFramework">
 * Java Collections Framework</a>.
 *
 * @apiNote
 * An {@link Enumeration} can be converted into an {@code Iterator} by
 * using the {@link Enumeration#asIterator} method.
 *
 * @param <E> the type of elements returned by this iterator
 *
 * @author  Josh Bloch
 * @see Collection
 * @see ListIterator
 * @see Iterable
 * @since 1.2
 */
public interface Iterator<E> {
    /**
     * Returns {@code true} if the iteration has more elements.
     * (In other words, returns {@code true} if {@link #next} would
     * return an element rather than throwing an exception.)
     *
     * @return {@code true} if the iteration has more elements
     */
    boolean hasNext();

    /**
     * Returns the next element in the iteration.
     *
     * @return the next element in the iteration
     * @throws NoSuchElementException if the iteration has no more elements
     */
    E next();

    /**
     * Removes from the underlying collection the last element returned
     * by this iterator (optional operation).  This method can be called
     * only once per call to {@link #next}.
     * <p>
     * The behavior of an iterator is unspecified if the underlying collection
     * is modified while the iteration is in progress in any way other than by
     * calling this method, unless an overriding class has specified a
     * concurrent modification policy.
     * <p>
     * The behavior of an iterator is unspecified if this method is called
     * after a call to the {@link #forEachRemaining forEachRemaining} method.
     *
     * @implSpec
     * The default implementation throws an instance of
     * {@link UnsupportedOperationException} and performs no other action.
     *
     * @throws UnsupportedOperationException if the {@code remove}
     *         operation is not supported by this iterator
     *
     * @throws IllegalStateException if the {@code next} method has not
     *         yet been called, or the {@code remove} method has already
     *         been called after the last call to the {@code next}
     *         method
     */
    default void remove() {
        throw new UnsupportedOperationException("remove");
    }

    /**
     * Performs the given action for each remaining element until all elements
     * have been processed or the action throws an exception.  Actions are
     * performed in the order of iteration, if that order is specified.
     * Exceptions thrown by the action are relayed to the caller.
     * <p>
     * The behavior of an iterator is unspecified if the action modifies the
     * collection in any way (even by calling the {@link #remove remove} method
     * or other mutator methods of {@code Iterator} subtypes),
     * unless an overriding class has specified a concurrent modification policy.
     * <p>
     * Subsequent behavior of an iterator is unspecified if the action throws an
     * exception.
     *
     * @implSpec
     * <p>The default implementation behaves as if:
     * <pre>{@code
     *     while (hasNext())
     *         action.accept(next());
     * }</pre>
     *
     * @param action The action to be performed for each element
     * @throws NullPointerException if the specified action is null
     * @since 1.8
     */
    default void forEachRemaining(Consumer<? super E> action) {
        Objects.requireNonNull(action);
        while (hasNext())
            action.accept(next());
    }
}
```



### ListIterator

*An iterator for lists that allows the programmer to **traverse the list in either direction, modify the list during iteration**, and **obtain the iterator's current position in the list**. A ListIterator has no current element; its cursor position always lies between the element that would be returned by a call to previous() and the element that would be returned by a call to next(). **An iterator for a list of length n has n+1 possible cursor positions**, as illustrated by the carets (^) below:*
                        *Element(0)   Element(1)   Element(2)   ... Element(n-1)*
   *cursor positions:  ^            ^            ^            ^                  ^*

*Note that **the remove and set(Object) methods are not defined in terms of the cursor position**; they are defined to operate on the last element returned by a call to next or previous().*

```java
public interface ListIterator<E> extends Iterator<E> {
    // Query Operations

    /**
     * Returns {@code true} if this list iterator has more elements when
     * traversing the list in the forward direction. (In other words,
     * returns {@code true} if {@link #next} would return an element rather
     * than throwing an exception.)
     *
     * @return {@code true} if the list iterator has more elements when
     *         traversing the list in the forward direction
     */
    boolean hasNext();

    /**
     * Returns the next element in the list and advances the cursor position.
     * This method may be called repeatedly to iterate through the list,
     * or intermixed with calls to {@link #previous} to go back and forth.
     * (Note that alternating calls to {@code next} and {@code previous}
     * will return the same element repeatedly.)
     *
     * @return the next element in the list
     * @throws NoSuchElementException if the iteration has no next element
     */
    E next();

    /**
     * Returns {@code true} if this list iterator has more elements when
     * traversing the list in the reverse direction.  (In other words,
     * returns {@code true} if {@link #previous} would return an element
     * rather than throwing an exception.)
     *
     * @return {@code true} if the list iterator has more elements when
     *         traversing the list in the reverse direction
     */
    boolean hasPrevious();

    /**
     * Returns the previous element in the list and moves the cursor
     * position backwards.  This method may be called repeatedly to
     * iterate through the list backwards, or intermixed with calls to
     * {@link #next} to go back and forth.  (Note that alternating calls
     * to {@code next} and {@code previous} will return the same
     * element repeatedly.)
     *
     * @return the previous element in the list
     * @throws NoSuchElementException if the iteration has no previous
     *         element
     */
    E previous();

    /**
     * Returns the index of the element that would be returned by a
     * subsequent call to {@link #next}. (Returns list size if the list
     * iterator is at the end of the list.)
     *
     * @return the index of the element that would be returned by a
     *         subsequent call to {@code next}, or list size if the list
     *         iterator is at the end of the list
     */
    int nextIndex();

    /**
     * Returns the index of the element that would be returned by a
     * subsequent call to {@link #previous}. (Returns -1 if the list
     * iterator is at the beginning of the list.)
     *
     * @return the index of the element that would be returned by a
     *         subsequent call to {@code previous}, or -1 if the list
     *         iterator is at the beginning of the list
     */
    int previousIndex();


    // Modification Operations

    /**
     * Removes from the list the last element that was returned by {@link
     * #next} or {@link #previous} (optional operation).  This call can
     * only be made once per call to {@code next} or {@code previous}.
     * It can be made only if {@link #add} has not been
     * called after the last call to {@code next} or {@code previous}.
     *
     * @throws UnsupportedOperationException if the {@code remove}
     *         operation is not supported by this list iterator
     * @throws IllegalStateException if neither {@code next} nor
     *         {@code previous} have been called, or {@code remove} or
     *         {@code add} have been called after the last call to
     *         {@code next} or {@code previous}
     */
    void remove();

    /**
     * Replaces the last element returned by {@link #next} or
     * {@link #previous} with the specified element (optional operation).
     * This call can be made only if neither {@link #remove} nor {@link
     * #add} have been called after the last call to {@code next} or
     * {@code previous}.
     *
     * @param e the element with which to replace the last element returned by
     *          {@code next} or {@code previous}
     * @throws UnsupportedOperationException if the {@code set} operation
     *         is not supported by this list iterator
     * @throws ClassCastException if the class of the specified element
     *         prevents it from being added to this list
     * @throws IllegalArgumentException if some aspect of the specified
     *         element prevents it from being added to this list
     * @throws IllegalStateException if neither {@code next} nor
     *         {@code previous} have been called, or {@code remove} or
     *         {@code add} have been called after the last call to
     *         {@code next} or {@code previous}
     */
    void set(E e);

    /**
     * Inserts the specified element into the list (optional operation).
     * The element is inserted immediately before the element that
     * would be returned by {@link #next}, if any, and after the element
     * that would be returned by {@link #previous}, if any.  (If the
     * list contains no elements, the new element becomes the sole element
     * on the list.)  The new element is inserted before the implicit
     * cursor: a subsequent call to {@code next} would be unaffected, and a
     * subsequent call to {@code previous} would return the new element.
     * (This call increases by one the value that would be returned by a
     * call to {@code nextIndex} or {@code previousIndex}.)
     *
     * @param e the element to insert
     * @throws UnsupportedOperationException if the {@code add} method is
     *         not supported by this list iterator
     * @throws ClassCastException if the class of the specified element
     *         prevents it from being added to this list
     * @throws IllegalArgumentException if some aspect of this element
     *         prevents it from being added to this list
     */
    void add(E e);
}
```