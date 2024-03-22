## Introduction

[Gson](https://github.com/google/gson) is a Java library that can be used to convert Java Objects into their JSON representation. It can also be used to convert a JSON string to an equivalent Java object. Gson can work with arbitrary Java objects including pre-existing objects that you do not have source-code of.

> [!Note]
> 
> Gson is currently in maintenance mode; existing bugs will be fixed, but large new features will likely not be added.


GSON provide two ways to exclude fields from JSON by GsonBuilder:

- `@Expose Annotation`</br>
  By using the @Expose annotations and then using the excludeFieldsWithoutExposeAnnotation() method on the GsonBuilder will ignore all fields except the ones that have been exposed using the @Expose annotation.
- `Custom Annotation`</br>
  By defining a custom annotation and ignoring fields that are annotated with exclusion class by extending ExclusionStrategy interface implementing that by using below GsonBuilder methods can ingnore/exclude fields from JSON.





## Links

-
