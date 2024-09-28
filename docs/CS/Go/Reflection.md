## Introduction



Interface{} 是空接口，可以表示任何类型，也就是说你可以把任何类型转换为空接口，它通常用于反射、类型断言，以减少重复代码，简化编程
在 Go 反射中，标准库为我们提供了两种类型 reflect.Value 和 reflect.Type 来分别表示变量的值和类型，并且提供了两个函数 reflect.ValueOf 和 reflect.TypeOf 分别获取任意对象的 reflect.Value 和 reflect.Type

```go
func main() {
	o := interface{}
	t := reflect.TypeOf(o)
	fmt.Printf("type:", t)


	v:= reflect.ValueOf(o)
	fmt.Printf("Fields:", v)


	for i:=0; i< t.NumField(); i++ {
		f := t.Field(i)
		val := v.Field(i).interface()
	}

	for i:=0; i< t.NumMethod(); i++ {
		m := t.Method(i)
		fmt.Printf("%6s: %v\n", m.Name, m.Type)
	}
}
```



这两个函数的参数都是空接口interface{}，内部存储了即将被反射的变量。因此，反射与接口之间存在很强的联系。可以说，不理解接口就无法深入理解反射。

可以将reflect.Value看作反射的值，reflect.Type看作反射的实际类型。其中，reflect.Type是一个接口，包含和类型有关的许多方法签名，例如Align方法、String方法等。

reflect.Value提供了Elem方法返回指针或接口指向的数据 如果Value存储的不是指针或接口，则使用Elem方法时会出错，因此在使用时要非常小心

通过如下reflect.TypeOf函数对于reflect.Type的构建过程可以发现，其实现原理为将传递进来的接口变量转换为底层的实际空接口emptyInterface，并获取空接口的类型值。reflect.Type实质上是空接口结构体中的typ字段，其是rtype类型，Go语言中任何具体类型的底层结构都包含这一类型。

生成reflect.Value的原理也可以从reflect.ValueOf函数的生成方法中看出端倪。reflect.ValueOf函数的核心是调用了unpackEface函数。

reflect.Value包含了接口中存储的值及类型，除此之外还包含了特殊的flag标志 flag标记以位图的形式存储了反射类型的元数据
flag的低5位存储了类型的标志，利用flag.kind方法有助于快速知道反射存储的类型
低6～10位代表了字段的一些特征，例如该字段是否是可以外部访问的、是否可以寻址、是否是方法等
flag的其余位存储了方法的index序号，代表第几个方法。只有在当前的value是方法类型时才会用到。例如第5号方法，其存储的位置为5<<10

flagIndir是最让人困惑的标志，代表间接的。我们知道存储在反射或接口中的值都是指针

另外，容器类型如切片、哈希表、通道也被认为是间接的，因为它们也需要当前容器的指针间接找到存储在其内部的元素

Interface核心方法调用了packEface函数。


## Links