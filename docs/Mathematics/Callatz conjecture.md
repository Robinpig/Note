## Introduction





对任意正整数 n($n\in Z^+$) 若n为偶数则除以二, 若n为奇数则乘3再减1, 如此反复, 其结果最终必然达到1

$$
f(n) =
	\begin{cases}
	\dfrac n2 \qquad \qquad if \quad n=0(mod 2) \\
	3n+1 \qquad if \quad n=1(mod 2)
	\end{cases}
	, \quad 必有k\in N 使得f^k(n)=1
$$



```java

public static int calltz(int num){
	int count = 0;
	if( num % 2 == 0){
		num = num/2;
	} else {
		
	}

}

```





## Links

- []