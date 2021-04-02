# Collection



![Collection](https://github.com/Robinpig/Note/raw/master/images/JDK/Collection.png)



## Collection

Allocate  memory when first element added.



Map



fail-fast

- Remove/add element in foreach will throw ConcurrentModificationException.
- Multiple threads remove/add element in Collection also throw ConcurrentModificationException.

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





