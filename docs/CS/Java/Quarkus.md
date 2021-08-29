



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

