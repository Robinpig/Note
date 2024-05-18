## Introduction
 
Lombok能以简单的注解形式来简化java代码，提高开发人员的开发效率。例如开发中经常需要写的javabean，都需要花时间去添加相应的getter/setter，也许还要去写构造器、equals等方法，而且需要维护，当属性多时会出现大量的getter/setter方法，这些显得很冗长也没有太多技术含量，一旦修改属性，就容易出现忘记修改对应方法的失误。

Lombok能通过注解的方式，在编译时自动为属性生成构造器、getter/setter、equals、hashcode、toString方法。出现的神奇就是在源码中没有getter和setter方法，但是在编译生成的字节码文件中有getter和setter方法。这样就省去了手动重建这些代码的麻烦，使代码看起来更简洁些。

 Lombok的使用跟引用jar包一样，可以从maven仓库引入依赖，同时IDE还需要安装插件。

## 注解

### @Data

  @Data集合了@ToString、@EqualsAndHashCode、@Getter/@Setter、@RequiredArgsConstructor的所有特性 ，@Data注解在类上，会为类的所有属性自动生成setter/getter、equals、canEqual、hashCode、toString方法，如为final属性，则不会为该属性生成setter方法。 

### @Getter/@Setter

 使用@Getter/@Setter注解，此注解在属性上，可以为相应的属性自动生成Getter/Setter方法 

### @NonNull

该注解用在属性或构造器上，Lombok会生成一个非空的声明，可用于校验参数，能帮助避免空指针。

### @Cleanup

 @Cleanup 注解可以帮助我们调用 close 方法，并且放到 try/finally 处理块中 。

### @EqualsAndHashCode

 该注解需应用在类上，使用该注解，lombok会为我们生成 equals(Object other) 和 hashcode() 方法，包括所有非静态属性和非transient的属性，
 
  exclude 属性排除某些字段，
 of 属性指定某些字段，也可以通过 callSuper 属性在重写的方法中使用父类的字段，这样我们可以更灵活的定义bean的比对 。

### @ToString

类使用@ToString注解，Lombok会生成一个toString()方法，默认情况下，会输出类名、所有属性（会按照属性定义顺序），用逗号来分割。

通过将`includeFieldNames`参数设为true，就能明确的输出toString()属性。这一点是不是有点绕口，通过代码来看会更清晰些。

### @NoArgsConstructor, @RequiredArgsConstructor and @AllArgsConstructor

Lombok没法实现多种参数构造器的重载。

 以上三个注解分别为我们生成无参构造器，指定参数构造器和包含所有参数的构造器，默认情况下，`@RequiredArgsConstructor`, `@AllArgsConstructor` 生成的构造器会对所有标记 `@NonNull` 的属性做非空校验。 

 `@RequiredArgsConstructor` 注解生成有参数构造器时只会包含有 final 和 `@NonNull` 标识的 field，同时我们可以指定 staticName 通过生成静态方法来构造对象 。

### @Builder

函数式编程或者说流式的操作越来越流行，应用在大多数语言中，让程序更具更简介，可读性更高，编写更连贯，`@Builder`就带来了这个功能，生成一系列的builder API，该注解也需要应用在类上。

### @Log

该注解需要应用到类上，在编写服务层，需要添加一些日志，以便定位问题，我们通常会定义一个静态常量Logger，然后应用到我们想日志的地方。

### @Accessors

- chain setter方法返回值为此对象
- fluent 在chain基础上将setter和getter方法名改为属性名
- prefix  prefix用于忽视指定前缀，修改getter和setter方法的方法名（遵守驼峰命名 

# Lombok工作原理分析

自动生成的代码到底是如何产生的呢？

核心之处就是对于注解的解析上。JDK5引入了注解的同时，也提供了两种解析方式。

- 运行时解析

运行时能够解析的注解，必须将@Retention设置为RUNTIME，这样就可以通过反射拿到该注解。java.lang,reflect反射包中提供了一个接口AnnotatedElement，该接口定义了获取注解信息的几个方法，Class、Constructor、Field、Method、Package等都实现了该接口，对反射熟悉的朋友应该都会很熟悉这种解析方式。

- 编译时解析

编译时解析有两种机制，分别简单描述下：

1）Annotation Processing Tool

apt自JDK5产生，JDK7已标记为过期，不推荐使用，JDK8中已彻底删除，自JDK6开始，可以使用Pluggable Annotation Processing API来替换它，apt被替换主要有2点原因：

- api都在com.sun.mirror非标准包下
- 没有集成到javac中，需要额外运行

2）Pluggable Annotation Processing API

[JSR 269](https://jcp.org/en/jsr/detail?id=269)自JDK6加入，作为apt的替代方案，它解决了apt的两个问题，javac在执行的时候会调用实现了该API的程序，这样我们就可以对编译器做一些增强，这时javac执行的过程如下：
![这里写图片描述](http://img.blog.csdn.net/20160908130644281)

Lombok本质上就是一个实现了“[JSR 269 API](https://www.jcp.org/en/jsr/detail?id=269)”的程序。在使用javac的过程中，它产生作用的具体流程如下：

1. javac对源代码进行分析，生成了一棵抽象语法树（AST）
2. 运行过程中调用实现了“JSR 269 API”的Lombok程序
3. 此时Lombok就对第一步骤得到的AST进行处理，找到@Data注解所在类对应的语法树（AST），然后修改该语法树（AST），增加getter和setter方法定义的相应树节点
4. javac使用修改后的抽象语法树（AST）生成字节码文件，即给class增加新的节点（代码块）

拜读了Lombok源码，对应注解的实现都在HandleXXX中，比如@Getter注解的实现时HandleGetter.handle()。还有一些其它类库使用这种方式实现，比如[Google Auto](https://github.com/google/auto)、[Dagger](http://square.github.io/dagger/)等等。

## Lombok的优缺点

优点：

1. 能通过注解的形式自动生成构造器、getter/setter、equals、hashcode、toString等方法，提高了一定的开发效率
2. 让代码变得简洁，不用过多的去关注相应的方法
3. 属性做修改时，也简化了维护为这些属性所生成的getter/setter方法等

缺点：

1. **不支持多种参数构造器的重载**
2. 虽然省去了手动创建getter/setter方法的麻烦，但大大降低了源代码的可读性和完整性，降低了阅读源代码的舒适度

##  总结

Lombok虽然有很多优点，但Lombok更类似于一种IDE插件，项目也需要依赖相应的jar包。Lombok依赖jar包是因为编译时要用它的注解，为什么说它又类似插件？因为在使用时，eclipse或IntelliJ IDEA都需要安装相应的插件，在编译器编译时通过操作AST（抽象语法树）改变字节码生成，变向的就是说它在改变java语法。它不像spring的依赖注入或者mybatis的ORM一样是运行时的特性，而是编译时的特性。这里我个人最感觉不爽的地方就是对**插件的依赖**！因为Lombok只是省去了一些人工生成代码的麻烦，但IDE都有快捷键来协助生成getter/setter等方法，也非常方便。