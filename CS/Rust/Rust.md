# Rust


Ownership 

	- 缓存切换会消耗性能 分配内存也会消耗时钟周期
	- 每个值只有一个变量作为所有者 作用域结束就销毁
Struct

	- struct 可变性是整体的 要么都可变或都不可变
	- 可以通过简洁赋值法使用相同类型对象属性来赋值
Match / let 

	If-let是match的唯一子项，用以简化匹配项及冗余代码
Collection

	- HashMap 一旦数据插入 所有权即交给map
	- 动态数组 
	
Panic
	
范型
	
Closure  

指针

引用
	循环引用
并发
