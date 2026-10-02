



```shell
mvn io.quarkus:quarkus-maven-plugin:1.4.1.Final:create \
-DprojectGroupId=com.yh \
-DprojectArtifaceId=quarkus \
-Dclassname="com.yh.quarkus.HelloResource" \
-Dpath="/hello"
```





```shell
 ./mvnw clean compile quarkus:dev
```



```properties
# application.properties
quarkus.http.cors=true
```

## Links

- [Introduction](/docs/CS/Java/AspectJ.md)
- [Introduction](/docs/CS/Java/Codec.md)
- [Introduction](/docs/CS/Java/Disruptor.md)
- [Introduction](/docs/CS/Java/Ehcache.md)
- [Introduction](/docs/CS/Java/Gson.md)
- [Introduction](/docs/CS/Java/Guava_Cache.md)
