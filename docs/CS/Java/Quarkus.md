



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

- [AspectJ](/docs/CS/Java/AspectJ.md)
- [Codec](/docs/CS/Java/Codec.md)
- [Disruptor](/docs/CS/Java/Disruptor.md)
- [Ehcache](/docs/CS/Java/Ehcache.md)
- [Gson](/docs/CS/Java/Gson.md)
- [Guava_Cache](/docs/CS/Java/Guava_Cache.md)
