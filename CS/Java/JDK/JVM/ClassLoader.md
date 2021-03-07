# ClassLoader



## ClassLoader Type

- BootstrapClassLoader(启动类加载器)

  C++实现,

- ExtensionClassLoader(扩展类加载器) 

- AppClassLoader(应用程序类加载器)

  继承于Ext类加载器

  

## 双亲委派模型 

防止重复加载 Java核心API不被篡改 
重写loadClass方法绕过双亲委托

破坏双亲委托

- Tomcat的WebApplicationClassLoader
- Java的SPI机制 JDBC的实现



## 加载流程 

加载->验证->准备->解析->初始化



