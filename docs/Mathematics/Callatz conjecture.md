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


考拉兹猜想"在变化过程中必然遵循的一条规律-白言规则。它指出：按照考拉兹猜想的运算规则，任一正整数都将会转变到LiKe第二数列{3^n-1∣n∈Z+}中的数；所得3^n-1 将会变为更小的3^n-1并最终变为8回到1

https://cloud.tencent.com/developer/article/2041862?cps_key=1d358d18a7a17b4a6df8d67a62fd3d3d






## Links

- []