# Branch Prediction



说来也是巧最近在看 Dubbo 源码，然后发现了一处很奇怪的代码，于是就有了这篇文章，让我们来看一下这段代码，它属于 `ChannelEventRunnable`，这个 runnable 是 Dubbo IO 线程创建，将此任务扔到业务线程池中处理。

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa990hp2fibELUY5Z2jZkCZ8A5D03amaUicHHRElosdiceRIj963tIuKIib2A/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

看到没，把 `state == ChannelState.RECEIVED` 拎出来独立一个 if，而其他的 state 还是放在 switch 里面判断。



我当时脑子里就来回扫描，想想这个到底有什么花头，奈何知识浅薄一脸懵逼。

于是就开始了一波探险之旅！

## 原来是 CPU 分支预测

遇到问题当然是问搜索引擎了，一般而言我会同时搜索各大引擎，咱这也不说谁比谁好，反正有些时候度娘还是不错的，比如这次搜索度娘给的结果比较靠前，google 较靠后。

一般搜索东西我都喜欢先在官网上搜，找不到了再放开搜，所以先这么搜 `site:xxx.com key`。



## Dubbo 官网的博客

> 现代 CPU 都支持分支预测 (branch prediction) 和指令流水线 (instruction pipeline)，这两个结合可以极大提高 CPU 效率。对于像简单的 if 跳转，CPU 是可以比较好地做分支预测的。但是对于 switch 跳转，CPU 则没有太多的办法。switch 本质上是根据索引，从地址数组里取地址再跳转。

也就是说 if 是跳转指令，如果是简单的跳转指令的话 CPU 可以**利用分支预测来预执行指令**，而 switch 是要先根据值去一个类似数组结构找到对应的地址，然后再进行跳转，这样的话 CPU 预测就帮不上忙了。

然后又因为一个 channel 建立了之后，**超过99.9%情况它的 state 都是 ChannelState.RECEIVED**，因此就把这个状态给挑出来，这样就能利用 CPU 分支预测机制来提高代码的执行效率。

并且还给出了 Benchmark 的代码，就是通过随机生成 100W 个 state，并且 99.99% 是  ChannelState.RECEIVED，然后按照以下两种方式来比一比（这 benchSwitch 官网的例子名字打错了，我一开始没发现后来校对文章才发现）。

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa9bXA8OwP98jsiaNSgIqyxLiaPulmYkjMia50iandlO0EbnozmxnoBjbcVLg/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

虽然博客也给出了它的对比结果，但是我还是本地来跑一下看看结果如何，其实 JMH 不推荐在 ide 里面跑，但是我懒，直接 idea 里面跑了。

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa9MsKlw8CDQiaj9dyllAhoHbmMjvU2JWYZf1G3WDLYcSaoEhljEUNpdvQ/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

从结果来看确实通过 if 独立出来代码的执行效率更高（注意这里测的是吞吐），博客还提出了这种技巧可以放在性能要求严格的地方，也就是一般情况下没必要这样特殊做。

至此我们已经知道了这个结论是对的，不过我们还需要深入分析一波，首先得看看  if 和 switch 的执行方式到底差别在哪里，然后再看看 CPU 分支预测和指令流水线的到底是干啥的，为什么会有这两个东西？

## if vs switch

我们先简单来个小 demo 看看 if 和 switch 的执行效率，其实就是添加一个全部是 if else 控制的代码， switch 和 if + switch 的不动，看看它们之间对比效率如何（此时还是 RECEIVED 超过99.9%）。

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa9Yl2bNWJOxhb2W9wh99YBq3ayOTnDO1iafmjI7gQLBwIRCPXLXibEommA/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

来看一下执行的结果如何：

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa9hya0ic5qNRRv03JbvGHpWBlPMhMChnsGp5CRdZGPMbSXg920rKLjYkA/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

好家伙，我跑了好几次，这全 if 的比 if + switch 强不少啊，所以是不是源码应该全改成 if else 的方式，你看这吞吐量又高，还不会像现在一下 if 一下又 switch 有点不伦不类的样子。

我又**把 state 生成的值改成随机的**，再来跑一下看看结果如何：

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa9stWkHXPcTU6TVqkSevjhqxt3nicD7hyhpFEGIvq18NLVmXqmbv9c2Dg/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

我跑了多次还是 if 的吞吐量都是最高的，怎么整这个全 if 的都是最棒滴。

## 反编译 if 和 switch

在我的印象里这个 switch 应该是优于 if 的，不考虑 CPU 分支预测的话，当从字节码角度来说是这样的，我们来看看各自生成的字节码。

**先看一下 switch 的反编译**，就截取了关键部分。

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa9L2DOKFz7icExcJFXxicjnLIxva3hFLc9dyEfsA7xafEEHNyIIMmmHdjw/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

也就是说 switch 生成了一个 tableswitch，上面的 getstatic 拿到值之后可以根据索引直接查这个 table，然后跳转到对应的行执行即可，也就是时间复杂度是 O(1)。

比如值是 1 那么直接跳到执行 64 行，如果是 4 就直接跳到 100 行。

关于 switch 还有一些小细节，**当 swtich 内的值不连续且差距很大的时候，生成的是 lookupswitch**，按网上的说法是二分法进行查询（我没去验证过），时间复杂度是 O(logn)，不是根据索引直接能找到了，我看生成的 lookup 的样子应该就是二分了，因为按值大小排序了。

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa9jicy4OVaBdJ2kZp4Qn2O6RzGceaaWXbk1micoPuCWVvRoAKcLDVOiaEqw/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

还有当 **switch 里面的值不连续但是差距比较小的时候，还是会生成 tableswtich 不过填充了一些值**，比如这个例子我 switch 里面的值就 1、3、5、7、9，它自动填充了2、4、6、8 都指到 default 所跳的行。

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa9t96MGsJ6A3VqeFCds3XyAnst1Sj7yWyLiaedZ8w3sGz3aKwKQicAmcuQ/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

**让我们再来看看 if 的反编译结果**：

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa9wjYdz6GAjOKFXKIhib1BUszoaYMOdeZD0zopOoX6xRexibQWPyAUjEjg/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

可以看到 if 是每次都会取出变量和条件进行比较，而 switch 则是取一次变量之后查表直接跳到正确的行，从这方面来看 switch 的效率应该是优于 if 的。当然如果 if 在第一次判断就过了的话也就直接 goto 了，不会再执行下面的哪些判断了。

所以从生成的字节码角度来看 switch 效率应该是大于 if 的，但是从测试结果的角度来看 if 的效率又是高于 switch 的，不论是随机生成 state，还是 99.99% 都是同一个 state 的情况下。

首先 CPU 分支预测的优化是肯定的，那关于随机情况下 if 还是优于 switch 的话这我就有点不太确定为什么了，可能是 JIT 做了什么优化操作，或者是随机情况下分支预测成功带来的效益大于预测失败的情形？

难道是我枚举值太少了体现不出 switch 的效果？不过在随机情况下 switch 也不应该弱于 if 啊，我又加了 7 个枚举值，一共 12 个值又测试了一遍，结果如下：

![Image](data:image/gif;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQImWNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==)

好像距离被拉近了，我看有戏，于是我背了波 26 个字母，实不相瞒还是唱着打的字母。

![Image](data:image/gif;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQImWNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==)

扩充了分支的数量后又进行了一波测试，这次 swtich 争气了，终于比 if 强了。

![Image](data:image/gif;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQImWNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==)

> 题外话: 我看网上也有对比 if 和 switch 的，它们对比出来的结果是 switch 优于 if，首先 jmh 就没写对，定义一个常量来测试 if 和 switch，并且测试方法的 result 写了没有消费，这代码也不知道会被 JIT 优化成啥样了，写了几十行，可能直接优化成 return 某个值了。

## 小结一下测试结果

对比了这么多我们来小结一下。

首先**对于热点分支**将其从 switch 提取出来用 if 独立判断，充分利用 CPU 分支预测带来的便利确实优于纯 swtich，从我们的代码测试结果来看，大致吞吐量高了两倍。

而**在热点分支的情形下**改成纯 if 判断而不是 if + swtich的情形下，吞吐量提高的更多。是纯 switch 的 3.3 倍，是 if + switch 的 1.6 倍。

**在随机分支的情形下**，三者差别不是很大，但是还是纯 if 的情况最优秀。

但是从字节码角度来看其实 switch 的机制效率应该更高的，不论是 O(1) 还是 O(logn)，但是从测试结果的角度来说不是的。

在选择条件少的情况下 if 是优于 switch 的，这个我不太清楚为什么，可能是在值较少的情况下查表的消耗相比带来的收益更大一些？有知道的小伙伴可以在文末留言。

在选择条件很多的情况下 switch 是优于 if 的，再多的选择值我就没测了，大伙有兴趣可以自己测测，不过趋势就是这样的。

## CPU 分支预测

接下来咱们再来看看这个分支预测到底是怎么弄的，为什么会有分支预测这玩意，不过在谈到分支预测之前需要先介绍下指令流水线（Instruction pipelining），也就是现代微处理器的 pipeline。

CPU 本质就是取指执行，而取指执行我们来看下五大步骤，分别是获取指令(IF)、指令解码(ID)、执行指令(EX)、内存访问(MEM)、写回结果(WB)，再来看下维基百科上的一个图。

![Image](data:image/gif;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQImWNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==)

当然步骤实际可能更多，反正就是这个意思需要经历这么多步，所以说一次执行可以分成很多步骤，那么这么多步骤就可以并行，来提升处理的效率。

所以说指令流水线就是试图用一些指令**使处理器的每一部分保持忙碌，方法是将传入的指令分成一系列连续的步骤，由不同的处理器单元执行，不同的指令部分并行处理。**

就像我们工厂的流水线一样，我这个奥特曼的脚拼上去了马上拼下一个奥特曼的脚，我可不会等上一个奥特曼的都组装完了再组装下一个奥特曼。

![Image](data:image/gif;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQImWNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==)

当然也没有这么死板，不一定就是顺序执行，有些指令在等待而后面的指令其实不依赖前面的结果，所以可以提前执行，这种叫**乱序执行**。

我们再说回我们的分支预测。

这代码就像我们的人生一样总会面临着选择，只有做了选择之后才知道后面的路怎么走呀，但是事实上发现这代码经常走的是同一个选择，于是就想出了一个分支预测器，让它来预测走势，提前执行一路的指令。

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa9Xoketp9z5KUjBOSp896jZTwfo3TRa9PVs4vZDiaibfe0ujGT7Fw2NJfQ/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

那预测错了怎么办？这和咱们人生不一样，它可以**把之前执行的结果全抛了然后再来一遍**，但是也有影响，也就是流水线越深，错的越多浪费的也就越多，**错误的预测延迟是10至20个时钟周期之间**，所以还是有副作用的。

简单的说就是通过分支预测器来预测将来要跳转执行的那些指令，然后预执行，这样到真正需要它的时候可以直接拿到结果了，提升了效率。

分支预测又分了很多种预测方式，有静态预测、动态预测、随机预测等等，从维基百科上看有16种。

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa93EEk3OZSS43tj9B828EmlYQnSMkXh7IwNa9b9QmjibMgRV2fdz5EIgg/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

我简单说下我提到的三种，**静态预测**就是愣头青，就和蒙英语选择题一样，我管你什么题我都选A，也就是说它会预测一个走势，一往无前，简单粗暴。

**动态预测**则会根据历史记录来决定预测的方向，比如前面几次选择都是 true ，那我就走 true 要执行的这些指令，如果变了最近几次都是 false ，那我就变成 false 要执行的这些指令，其实也是利用了局部性原理。

**随机预测**看名字就知道了，这是蒙英语选择题的另一种方式，瞎猜，随机选一个方向直接执行。

还有很多就不一一列举了，各位有兴趣自行去研究，顺便提一下在 2018 年谷歌的零项目和其他研究人员公布了一个名为 Spectre 的灾难性安全漏洞，其可利用 CPU 的分支预测执行泄漏敏感信息，这里就不展开了，文末会附上链接。

之后又有个名为 BranchScope 的攻击，也是利用预测执行，所以说每当一个新的玩意出来总是会带来利弊。

至此我们已经知晓了什么叫指令流水线和分支预测了，也理解了 Dubbo 为什么要这么优化了，但是文章还没有结束，我还想提一提这个 stackoverflow 非常有名的问题，看看这数量。



## 为什么处理有序数组要比非有序数组快？

这个问题在那篇博客开头就被提出来了，很明显这也是和分支预测有关系，既然看到了索性就再分析一波，大伙可以在脑海里先回答一下这个问题，毕竟咱们都知道答案了，看看思路清晰不。

就是下面这段代码，数组排序了之后循环的更快。



然后各路大神就蹦出来了，我们来看一下首赞的大佬怎么说的。

一开口就是，直击要害。

> You are a victim of branch prediction fail.

紧接着就上图了，一看就是老司机。

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa9vDMp8lMnLS87P1A7PvgxTzdiaKKHkpOJ2paYmT5TBiaxvYMa41URJxicA/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

他说让我们回到 19世纪，一个无法远距离交流且无线电还未普及的时候，如果是你这个铁路交叉口的扳道工，当火车快来的时候，你如何得知该扳哪一边？

火车停车再重启的消耗是很大的，每次到分叉口都停车，然后你问他，哥们去哪啊，然后扳了道，再重启就很耗时，怎么办？猜！

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa9lAEZ4HtfqJkc75hic3IJttLM8w0ohfnpMdFcrakIF7tZYE0qiaereoYw/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

猜对了火车就不用停，继续开。猜错了就停车然后倒车然后换道再开。

所以就看猜的准不准了！搏一搏单车变摩托。

然后大佬又指出了关键代码对应的汇编代码，也就是跳转指令了，这对应的就是火车的岔口，该选条路了。

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa9WicvEVFrwjHMndwD0THWibLtdk6xQcepIbErECbXj9SMFoibVKrpIkm5A/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

后面我就不分析了，大伙儿应该都知道了，排完序的数组执行到值大于 128 的之后肯定全部大于128了，所以每次分支预测的结果都是对了！所以执行的效率很高。

而没排序的数组是乱序的，所以很多时候都会预测错误，而预测错误就得指令流水线排空啊，然后再来一遍，这速度当然就慢了。

所以大佬说这个题主你是分支预测错误的受害者。

最终大佬给出的修改方案是咱不用 if 了，惹不起咱还躲不起嘛？直接利用位运算来实现这个功能，具体我就不分析了，给大家看下大佬的建议修改方案。

![Image](https://mmbiz.qpic.cn/mmbiz_png/azicia1hOY6QibEh7mVicEt6icC8A9fpiaJYa9mW89Oia2dyluibIwPtJ5KUlY8tJgfN0SPB6HGI4lqo7oicriaZDNSnw00A/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

## 最后

这篇文章就差不多了，今天就是从 Dubbo 的一段代码开始了探险之旅，分析了波 if 和 switch，从测试结果来看 Dubbo 的这次优化还不够彻底，应该全部改成 if else 结构。

而 swtich 从字节码上看是优于 if 的，但是从测试结果来看在分支很多的情况下能显示出优势，一般情况下还是打不过 if 。

然后也知晓了什么叫指令流水线，这其实就是结合实际了，流水线才够快呀，然后分支预测预执行也是一个提高效率的方法，当然得猜的对，不然分支预测错误的副作用还是无法忽略的，所以对分支预测器的要求也是很高的。

