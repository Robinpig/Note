## Introduction


Spring Session是如何实现的，我们还是有必要了解了解~
其实它是通过Servlet规范中的Filter机制拦截了所有Servlet请求，偷梁换柱，将标准的Servlet请
求对象包装了一下，换成它自己的Request包装类对象，这样当程序员通过包装后的Request对象
的getSession方法拿Session时，是通过Spring拿Session，没Web容器什么事了。


- Sticky Session
- Replication
- Centerial



Spring Session makes it trivial to support clustered sessions without being tied to an application container specific solution.



HttpSession





## Links

- [Spring](/docs/CS/Java/Spring/Spring.md)