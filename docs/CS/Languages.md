## Introduction


> Once a language is out in the field, the ugly reality of compatibility with existing code sets in.


An object-oriented program is made of objects. Each object has a specific functionality, exposed to its users, and a hidden implementation. 
Many objects in your programs will be taken “off-the-shelf” from a library; others will be custom-designed. 
Whether you build an object or buy it might depend on your budget or time. But, basically, as long as an object satisfies your specifications, you don’t care how the functionality is implemented.

Traditional structured programming consists of designing a set of procedures (or algorithms) to solve a problem. Once the procedures are determined, the traditional next step was to find appropriate ways to store the data. 
This is why the designer of the Pascal language, Niklaus Wirth, called his famous book on programming Algorithms + Data Structures = Programs (Prentice Hall, 1976). 
Notice that in Wirth’s title, algorithms come first, and data structures second. This reflects the way programmers worked at that time.
First, they decided on the procedures for manipulating the data; then, they decided what structure to impose on the data to make the manipulations easier. 
OOP reverses the order: puts the data first, then looks at the algorithms to operate on the data.


“A class specifies how objects are made. Think of classes as cookie cutters; objects are the cookies themselves. When you construct an object from a class, you are said to have created an instance of the class.


“Encapsulation (sometimes called information hiding) is a key concept in working with objects. Formally, encapsulation is simply combining data and behavior in one package and hiding the implementation details from the users of the object. The bits of data in an object are called its instance fields, and the procedures that operate on the data are called its methods. A specific object that is an instance of a class will have specific values of its instance fields. The set of those values is the current state of the object. Whenever you invoke a method on an object, its state may change.
The key to making encapsulation work is to have methods never directly access instance fields in a class other than their own. Programs should interact with object data only through the object’s methods. Encapsulation is the way to give an object its “black box” behavior, which is the key to reuse and reliability. This means a class may totally change how it stores its data, but as long as it continues to use the same methods to manipulate the data, no other object will know or care.

“When you start writing your own classes in Java, another tenet of OOP will make this easier: Classes can be built by extending other classes. Java, in fact, comes with a “cosmic superclass” called Object. All other classes extend this class. You will learn more about the Object class in the next chapter.

When you extend an existing class, the new class has all the properties and methods of the class that you extend. You then supply new methods and instance fields that apply to your new class only.
The concept of extending a class to obtain another class is called inheritance. 


“To work with OOP, you should be able to identify three key characteristics of objects:
• The object’s behavior—what can you do with this object, or what methods can you apply to it?
• The object’s state—how does the object react when you invoke those methods?
• The object’s identity—how is the object distinguished from others that may have the same behavior and state?”


“All objects that are instances of the same class share a family resemblance by supporting the same behavior. The behavior of an object is defined by the methods that you can call.”

“Next, each object stores information about what it currently looks like. This is the object’s state. An object’s state may change over time, but not spontaneously. A change in the state of an object must be a consequence of method calls. (If an object’s state changed without a method call on that object, someone broke encapsulation.)

However, the state of an object does not completely describe it, because each object has a distinct identity. For example, in an order processing system, two orders are distinct even if they request identical items.
Notice that the individual objects that are instances of a class always differ in their identity and usually differ in their state.

These key characteristics can influence each other. For example, the state of an object can influence its behavior. 
(If an order is “shipped” or “paid,” it may reject a method call that asks it to add or remove items. Conversely, if an order is “empty”—that is, no items have yet been ordered—it should not allow itself to be shipped.)”


### Relationships between Classes
“The most common relationships between classes are
• Dependence (“uses–a”)
• Aggregation (“has–a”)
• Inheritance (“is–a”)
The dependence, or “uses–a” relationship, is the most obvious and also the most general. For example, the Order class uses the Account class because Order objects need to access Account objects to check for credit status. But the Item class does not depend on the Account class, because Item objects never need to worry about customer accounts. Thus, a class depends on another class if its methods use or manipulate objects of that class.
Try to minimize the number of classes that depend on each other. The point is, if a class A is unaware of the existence of a class B, it is also unconcerned about any changes to B. (And this means that changes to B do not introduce bugs into A.) In software engineering terminology, you want to minimize the coupling between classes.
The aggregation, or “has–a” relationship, is easy to understand because it is concrete; for example, an Order object contains Item objects. Containment means that objects of class A contain objects of class B.”

#### Inheritance

The inheritance, or “is–a” relationship, expresses a relationship between a more special and a more general class. For example, a RushOrder class inherits from an Order class. The specialized RushOrder class has special methods for priority handling and a different method for computing shipping charges, but its other methods, such as adding items and billing, are inherited from the Order class. In general, if class D extends class C, class D inherits methods from class C but has more capabilities. (See the next chapter which discusses this important notion at some length.)
Many programmers use the UML (Unified Modeling Language) notation to draw class diagrams that describe the relationships between classes. You can see an example of such a diagram in Figure 4.2. You draw classes as rectangles, and relationships as arrows with various adornments.”


In C++, you need to declare a member function as virtual if you want dynamic binding. In Java, dynamic binding is the default behavior; if you do not want a method to be virtual, you tag it as final.


#### Objects and Object Variables
To work with objects, you first construct them and specify their initial state. Then you apply methods to the objects.

The object-oriented features of Java are comparable to those of C++. 
The major difference between Java and C++ lies in multiple inheritance, which Java has replaced with a simpler concept of interfaces.
Java has a richer capacity for runtime introspection than C++.

You should think of Java object variables as analogous to object pointers in C++.
The equivalent of the Java null reference is the C++ NULL pointer.



<div style="text-align: center;">

![Fig.1. Procedural vs. OO programming](img/P-vs-OO.png)

</div>

<p style="text-align: center;">
Fig.1. Procedural vs. OO programming.
</p>


Architecture-Neutral