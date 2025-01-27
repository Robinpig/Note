## Introduction

## 8

Lambda


## 9
### JShell

### 接口私有方法


Java8 带来了许多改变，其中之一就是 default 修饰的接口方法。这些方法改变了我们已知的接口，现在我们能够在接口中定义默认实现方法。如果你大量使用 default 方法在你的应用接口中，现在可以通过 JDK9 的接口私有方法来重构。

```
public interface PrivateInterface {

 private void printF(){
  System.out.println("lengleng");
 }

 default void getPassword(){
  printF();
  System.out.println("123456");
 }
}
 @Test
 public void testGetPassword() {
  var privateInterface = new PrivateInterfaceImpl();
  privateInterface.getPassword();
 }
```


## 10
### var 类型推断


var 是 Java10 版本中新出的特性，用它来定义局部变量。var 不是关键字，相当于一种动态类型，编译器根据变量所赋的值来推断类型。所以必须在定义变量的时候赋初始值。

```java
 @Test
 public void testJDK10VarLocalVariable(){
  var num1 = 1000;
  var num2 = 1.001;
  var str = "hello var";
  var list = new ArrayList<>();
  var map = new HashMap<>();
 }

 @Test
 public void testNoramlVariable(){
  int num1 = 1000;
  double num2 = 1.001;
  String str = "hello var";
  List list = new ArrayList<>();
  Map map = new HashMap();
 }
```
## 12

### switch 表达式

- 如下逻辑，当我们需要判断某天是否是工作日时候，需要大量的重复的 case 逻辑

```java
 @Test
 public void testNormalSwitch() {
  int day = 2;
  switch (day) {
  case 1:
  case 2:
  case 3:
  case 4:
  case 5:
   System.out.println("workday");
  case 6:
  case 7:
   System.out.println("weekend");
  default:
   System.out.println("invalid");
  }
 }
复制代码
```

- jdk12 可以通过的 switch 表达式简化如上逻辑

```
@Test
 public void testNewJdk12MultiSwitch() {
  var day = 2;
  switch (day) {
  case 1, 2, 3, 4, 5 -> System.out.println("workday");
  case 6, 7 -> System.out.println("weekend");
  default -> System.out.println("invalid");
  }
 }
复制代码
```

## 13
### Text Block

在我们日常的工作中，有时候需要用到一大段的字符串，这些字符串需要换行，需要排版，需要转义。在一个文本编辑器中，这当然是非常容易的事情。但是在 java 代码中，就是一个噩梦了。而新的文本块使用"""这个符号，进行拼接。

- 简化表达多行字符串，不需要转义；
- 增强可读性；

```java
 @Test
 public void testNormalString(){
  String text = "{" + "\n"
    +"    \"username\": \"lengleng\",\n"
    +"    \"password\": \"123456\" \n"
    +"}";
  System.out.println(text);
 }

 @Test
 public void testNewJdk13TextBlock(){
  var text = """
               {
                    "username": "lengleng",
                    "password": "123456"
               }
               """;
  System.out.println(text);
 }
复制代码
```


### Collection Factory 

since jdk9

- 通常希望在代码中创建一个集合（例如，List 或 Set ），并直接用一些元素填充它。实例化集合，几个 “add” 调用，使得代码重复。

```java
 @Test
 public void testNormal(){
  List<String> fruitsTmp = new ArrayList<>();
  fruitsTmp.add("apple");
  fruitsTmp.add("banana");
  fruitsTmp.add("orange");


  Map<Integer, String> numbersTmp = new HashMap<>();
  numbersTmp.put(1, "one");
  numbersTmp.put(2, "two");
  numbersTmp.put(3, "three");
 }
```

- 现在可以通过 of 方法来快速构建集合类型

```java
@Test
 public void testNewJdk9() {
  var fruits = List.of("apple", "banana", "orange");
  var numbers = Map.of(1, "one", 2, "two", 3, "three");
 }
```
## 14
### Records


Records 的目标是扩展 Java 语言语法，Records 为声明类提供了一种紧凑的语法，用于创建一种类中是“字段，只是字段，除了字段什么都没有”的类。通过对类做这样的声明，编译器可以通过自动创建所有方法并让所有字段参与 hashCode()等方法。干掉 lombok 只需要通过 record 声明即可完成实体字段的 get 和构造器方法。

```java
public record Demo(String username, String password) {

}
 @Test
 public void testJdk15Record() {
  var demo = new Demo("lengleng", "123456");
  System.out.println(demo.password());
  System.out.println(demo.username());
 }

```

## 15
### Sealed 类封闭


可扩展性不是面向对象编程的一个重要指标吗？为什么要限制可扩展性呢？其实，面向对象编程的最佳实践之一，就是要把可扩展性的限制在可以预测和控制的范围内，而不是无限的可扩展性。

- 通过 sealed 定义接口或者抽象类

```
public sealed interface Pet permits Cat {
}

```

- 分配权限的子类可以正常的实现此接口

```
public final class Cat implements Pet {
}
```

- 若没有子类没有分配权限，则编译直接报错

![img](https://p3-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/7245131cba0e4720beecb92472843a6a~tplv-k3u1fbpfcp-zoom-1.image)



## 17

### Record


## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)
