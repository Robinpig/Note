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



加载时机

1. 使用 new 关键字实例化对象的时候、读取或设置一个类的静态字段（被final修饰、已在编译期把结果放入常量池的静态字段除外）的时候，以及调用一个类的静态方法的时候。
2. 使用 java.lang.reflect 包的方法对类进行反射调用的时候，如果类没有进行过初始化，则需要先触发其初始化。
3. 当初始化一个类的时候，如果发现其父类还没有进行过初始化，则需要先触发其父类的初始化。
4. 当虚拟机启动时，用户需要指定一个要执行的主类（包含 main()方法的那个类），虚拟机会先初始化这个主类。
5. 当使用 JDK 1.7 的动态语言支持时，如果一个 java.lang.invoke.MethodHandle 实例最后的解析结果 REF_getStatic、REF_putStatic、REF_invokeStatic 的方法句柄，并且这个方法句柄所对应的类没有进行过初始化，则需要先触发其初始化。





## 加载流程 

1. Loading
2. Linking
   1. Verification
   2. Preparation
   3. Resolution
3. Initializtion
4. Using
5. Unloading

### Loading

负责从文件系统或者网络中加载Class文件，Class文件开头有特定Magic Number ， 4Byte

Classloader只负责class文件的加载，至于是否可运行，则由执行引擎决定

加载的类信息存放于称为方法区的内存空间，除了类信息，方法区还会存放运行时常量池信息，还可能包括字符串字面量和数字常量

常量池运行时加载到内存中，即运行时常量池

1. 通过一个类的全限定名获取定义此类的二进制字节流
   1. 本地系统获取网络获取，
   2. Web Appletzip压缩包获取，jar，war
   3. 运行时计算生成，
   4. 动态代理有其他文件生成，
   5. jsp专有数据库提取.class文件，
   6. 比较少见加密文件中获取，防止Class文件被反编译的保护措施
2. 将这个字节流所代表的的静态存储结果转化为方法区的运行时数据结构
3. 在内存中生成一个代表这个类的java.lang.Class对象，作为方法区这个类的各种数据访问入口



### Linking



### Verification

目的

确保Class文件的字节流中包含信息符合当前虚拟机要求，保证被加载类的正确性，不会危害虚拟机自身安全

四种验证

文件格式验证

CA FE BA BE(魔数，Java虚拟机识别)

主次版本号

常量池的常量中是否有不被支持的常量类型

指向常量的各种索引值中是否有指向不存在的常量或不符合类型的常量



### Preparation



### Resolution



### Initialization





### Using



### Unloading

