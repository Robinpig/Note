## Introduction







## MappedStatement

a StrictMap not support method overload.  throw Exception when contains in put.



```java
// Configuration
protected final Map<String, MappedStatement> mappedStatements = new StrictMap<MappedStatement>("Mapped Statements collection")
  .conflictMessageProducer((savedValue, targetValue) ->
                           ". please check " + savedValue.getResource() + " and " + targetValue.getResource());

// StrictMap
public V put(String key, V value) {
  if (containsKey(key)) {
    throw new IllegalArgumentException(name + " already contains value for " + key
        + (conflictMessageProducer == null ? "" : conflictMessageProducer.apply(super.get(key), value)));
  }
  if (key.contains(".")) {
    final String shortKey = getShortName(key);
    if (super.get(shortKey) == null) {
      super.put(shortKey, value);
    } else {
      super.put(shortKey, (V) new Ambiguity(shortKey));
    }
  }
  return super.put(key, value);
}
```