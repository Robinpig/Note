## Introduction

## Interpreter versus Compiler

By now, you might have understood that, any programming language is essentially a human-friendly formalism for writing instructions for a computer to follow.
These instructions are at some point translated into machine language, which is what the computer really understands.
These languages are composed of a set of basic operations whose execution is implemented in the hardware of the processor.

People often describe programming languages as either compiled or interpreted.
“Compiled” means that programs are translated into machine language and then executed by hardware; “interpreted” means that programs are read and executed by a software interpreter.
Usually C is considered a compiled language and Python is considered an interpreted language. But the distinction is not always clear-cut.

First, many languages can be either compiled or interpreted.
For example, there are C interpreters and Python compilers.
Second, there are languages like Java that use a hybrid approach, compiling programs into an intermediate language and then running the translated program in an interpreter.
Java uses an intermediate language called Java bytecode, which is similar to machine language, but it is executed by a software interpreter, the Java virtual machine (JVM).
Almost all high level programming languages have compilers and interpreters.

So being compiled or interpreted is not an intrinsic characteristic of a language; nevertheless, there are some general differences between compiled and interpreted languages.

Many interpreted languages support dynamic types, but compiled languages are usually limited to static types.
In a statically-typed language, you can tell by looking at the program what type each variable refers to. 
In a dynamically- typed language, you don’t always know the type of a variable until the pro- gram is running.
In general, static refers to things that happen at compile time (while a program is being compiled), and dynamic refers to things that happen at run time (while a program is running).
For example, in Python you can write a function like this:

```python
def add(x, y):
    return x + y
```

Looking at this code, you can’t tell what type x and y will refer to at run time. 
This function might be called several times, each time with values with different types.
Any values that support the addition operator will work; any other types will cause an exception or runtime error.
In C you would write the same function like this:

```c
int add(int x, int y) {
    return x + y;
}
```

The first line of the function includes *type declarations* for the parameters and the return value: x and y are declared to be integers,
which means that we can check at compile time whether the addition operator is legal for this type (it is).
The return value is also declared to be an integer.

Because of these declarations, when this function is called elsewhere in the program,
the compiler can check whether the arguments provided have the right type, and whether the return value is used correctly.

These checks happen before the program starts executing, so errors can be found earlier. More importantly, errors can be found in parts of the program that have never run.
Furthermore, these checks don’t have to happen at run time, which is one of the reasons compiled languages generally run faster than interpreted languages.

Declaring types at compile time also saves space. In dynamic languages, vari- able names are stored in memory while the program runs, and they are of ten accessible by the program.
For example, in Python the built-in function locals returns a dictionary that contains variable names and their values.

In compiled languages, variable names exist at compile-time but not at run time. The compiler chooses a location for each variable and records these locations as part of the compiled program.
The location of a variable is called its address.
At run time, the value of each variable is stored at its address, but the names of the variables are not stored at all (unless they are added by the compiler for purposes of debugging).

**Difference between compiler and interpreter**

- A complier converts the high level instruction into machine language while an interpreter converts the high level instruction into an intermediate form.
- Before execution, entire program is executed by the compiler whereas after translating the first line, an interpreter then executes it and so on.
- List of errors is created by the compiler after the compilation process while an interpreter stops translating after the first error.
- An independent executable file is created by the compiler whereas interpreter is required by an interpreted program each time.

## Script Languages

The term scripting language has never been formally defined, but here are the typical characteristics:

- Used often for system administration.
- Very casual with regard to typing of variables, e.g. no distinction between integer, floating-point or string variables.
- Lots of high-level operations intrinsic to the language, e.g. stack push/pop.
- Interpreted, rather than being compiled to the instruction set of the host machine.

Today many people prefer Python, as it is much cleaner and more elegant.
We look at three scripting languages: Shell, PERLand Python.

## Links

## References
