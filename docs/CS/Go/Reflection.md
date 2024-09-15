



Interface{} 是空接口，可以表示任何类型，也就是说你可以把任何类型转换为空接口，它通常用于反射、类型断言，以减少重复代码，简化编程
在 Go 反射中，标准库为我们提供了两种类型 reflect.Value 和 reflect.Type 来分别表示变量的值和类型，并且提供了两个函数 reflect.ValueOf 和 reflect.TypeOf 分别获取任意对象的 reflect.Value 和 reflect.Type