## Introduction

正常情况下 程序顺序执行(不考虑乱序) 但当某些事件发生的时候 需要有一个响应处理机制去打断当前执行流去处理事件 
有了此机制可以实现处理异常 响应事件 管理进程等操作 这就是接下来要讲到的中断机制

以下是常见的中断 广义的中断包括异常和我们常说的中断

中断和异常十分相似，不同之处在于，中断是被动的，异常是主动的

<table class="tg"><thead>
  <tr>
    <th class="tg-0lax" colspan="4">类别</th>
    <th class="tg-0lax">来源</th>
    <th class="tg-0lax">返回行为</th>
    <th class="tg-0lax">例子</th>
  </tr></thead>
<tbody>
  <tr>
    <td class="tg-0lax" rowspan="5">广义中断</td>
    <td class="tg-0lax" rowspan="2">异步中断(狭义中断)</td>
    <td class="tg-0lax" rowspan="2">中断(Interrupt)</td>
    <td class="tg-0lax">可屏蔽中断</td>
    <td class="tg-0lax" rowspan="2">来自I/O设备的信号</td>
    <td class="tg-0lax" rowspan="2">返回到下一条指令</td>
    <td class="tg-0lax">IRQ</td>
  </tr>
  <tr>
    <td class="tg-0lax">不可屏蔽中断</td>
    <td class="tg-0lax">电源掉电和物理存储器奇偶校验</td>
  </tr>
  <tr>
    <td class="tg-0lax" rowspan="3">同步中断(异常)</td>
    <td class="tg-0lax" colspan="2">陷阱(trap)</td>
    <td class="tg-0lax">主动的异常</td>
    <td class="tg-0lax">返回到下一条指令</td>
    <td class="tg-0lax">系统调用 信号机制</td>
  </tr>
  <tr>
    <td class="tg-0lax" colspan="2">故障(fault)</td>
    <td class="tg-0lax">可恢复错误</td>
    <td class="tg-0lax">返回到当前指令</td>
    <td class="tg-0lax">缺页异常</td>
  </tr>
  <tr>
    <td class="tg-0lax" colspan="2">终止(abort)</td>
    <td class="tg-0lax">不可恢复错误</td>
    <td class="tg-0lax">不会返回</td>
    <td class="tg-0lax">硬件错误</td>
  </tr>
</tbody>
</table>
> CPU在响应中断的时候是处理完当前指令后去check一下是否有中断 单指令是不可中断的



x86处理器的INTR和NMI接受外部中断请求信号 INTR接受可屏蔽中断请求 NMI接受不可屏蔽中断请求 标志寄存器EFLAGS中的IF标志位决定是否屏蔽可屏蔽中断请求

中断控制器与处理器相连 传统中断控制器为PIC 在SMP架构中 每个处理器都包含一个IOAPIC

处理器识别中断后 根据中断控制器传递的中断索引去IDT(*InterruptDescriptor Table*)中查询并执行中断处理程序 中断处理程序会负责保护现场 处理中断 恢复保存的现场



- [Linux Interrupt](/docs/CS/OS/Linux/Interrupt.md)



## Links

- [Linux Interrupt](/docs/CS/OS/Linux/Interrupt.md)
