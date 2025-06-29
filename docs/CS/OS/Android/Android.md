## Introduction



## Architecture


硬件抽象层



Android 采用了自己编写的 init 工具 通过自定义的一套配置文件管理系统服务的启动 
配置文件目录与其他 Linux 发行版在 `/etc` 下不同 Android 的在 `/system/etc` 下 为了兼容性将 `/etc` 链接到 `/system/etc` 下便于利用原有工具


Android 单独开发了一个libc库 Bionic 重新开发运行加载器 ld.so 
在 ELF 文件格式上做了扩充 对应设计了 Android 专用的 linker 程序
在应用层上 Android可以兼容 Linux, Linux 无法直接兼容 Android


Framework和类库是Android的核心，也是Android与其他以Linux内核为基础的操作系统的最大区别
它规定并实现系统的标准、 接口，构建Android的框架， 比如数据存储、 显示、 服务和应用程序管理等



## Discuss
支付宝以往的启动页较单一，无法较好地宣传和提升用户体验，需要对启动页进行能力升级
这个启动页上有个倒计时功能。这篇文章主要讲下这个倒计时的实现。
在Android上最常见的倒计时方案是CountDownTimer。在CountDownTimer的onTick刷新时间信息到TextView，在onFinish时结束计时。相信熟练的开发GG用不了一个上午就能搞定。
不过真的这么简单吗？先用CountDownTimer+TextView写个Demo看看效果
可以看到，显示3s停顿了一会儿之后倒计时直接结束了。看看日志
```
2023-02-20 11:57:53.109 31588-31588/com.eg.android.AlipayGphone D/TL_AlipaySplasher: [main] onTick: millisUntilFinished=2997
2022-02-20 11:57:57.609 31588-31588/com.eg.android.AlipayGphone D/TL_AlipaySplasher: [main] onFinish: 
```
就是说，2s和1s的时候没有回调onTick。
先来看一下CountDownTimer的核心代码(Android 8及以上的实现，8以下有些bug
```java
final long millisLeft = mStopTimeInFuture - SystemClock.elapsedRealtime();
if (millisLeft <= 0) {
    onFinish();
} else {
    long lastTickStart = SystemClock.elapsedRealtime();
    onTick(millisLeft);
    // take into account user's onTick taking time to execute
    long lastTickDuration = SystemClock.elapsedRealtime() - lastTickStart;
    long delay;
    if (millisLeft < mCountdownInterval) {
        // just delay until done
        delay = millisLeft - lastTickDuration;
        // special case: user's onTick took more than interval to
        // complete, trigger onFinish without delay
        if (delay < 0) delay = 0;
    } else {
        delay = mCountdownInterval - lastTickDuration;
        // special case: user's onTick took more than interval to
        // complete, skip to next interval
        while (delay < 0) delay += mCountdownInterval;
    }
    sendMessageDelayed(obtainMessage(MSG), delay);
}
```

这里的计数是通过延时Message来实现。如果下一个Message被执行之前，插入了很多其它的即时Message，那可能会导致我们计时的Message没有得到立即执行，从而出现延迟。当延迟超过了总计时时间，那直接onFinish() 了。
支付宝启动页Resume后，可以看到主线程有较多的任务需要执行

这也正是为什么3s过了一会儿直接计时结束的原因。
既然主线程繁忙，任务不能得到立即执行出现计时不准确。那我们换个办法：在子线程中计时，然后主线程中刷新时间信息。我们使用Timer + Handler（sendMessageAtFrontOfQueue）的方式。 结果发现，虽然计时准确了，但是界面刷新却是延迟和跳跃的

```
2023-02-21 11:14:13.112 31588-31806/com.eg.android.AlipayGphone D/TL_AlipaySplasher: [SplashCountDownTimer] onTick: millisUntilFinished=2998
2023-02-21 11:14:13.135 31588-31806/com.eg.android.AlipayGphone D/TL_AlipaySplasher: [main] refreshSkipBtnText: time=2998
2023-02-21 11:14:14.110 31588-31806/com.eg.android.AlipayGphone D/TL_AlipaySplasher: [SplashCountDownTimer] onTick: millisUntilFinished=1999
2023-02-21 11:14:15.109 31588-31806/com.eg.android.AlipayGphone D/TL_AlipaySplasher: [SplashCountDownTimer] onTick: millisUntilFinished=1000
2023-02-21 11:14:16.109 31588-31806/com.eg.android.AlipayGphone I/TL_AlipaySplasher: [SplashCountDownTimer] countDownSplash: onFinish
2023-02-21 11:14:16.141 31588-31806/com.eg.android.AlipayGphone D/TL_AlipaySplasher: [main] refreshSkipBtnText: time=1999
2023-02-21 11:14:16.173 31588-31806/com.eg.android.AlipayGphone D/TL_AlipaySplasher: [main] refreshSkipBtnText: time=1000
2023-02-21 11:14:16.173 31588-31806/com.eg.android.AlipayGphone D/TL_AlipaySplasher: [main] refreshSkipBtnText: gone
```

原因还是主线程有正在执行的任务，且任务耗时较长，导致丢到队首的任务没有得到立即执行。
0x02 解决方案
计时的问题已经解决，那接下来只需要解决及时刷新的问题。短时间治理主线程耗时任务不太现实。既然主线程繁忙，那何不在子线程中刷新UI呢。Android中提供了可以在独立线程中渲染的视图组件SurfaceView。SurfaceView具有以下特点：
1.
独立于 UI 线程：SurfaceView 在单独的线程中渲染内容，不会阻塞 UI 线程，因此适合处理复杂的图形计算和视频解码。
2.
硬件加速：SurfaceView 可以利用硬件加速，提高渲染性能。
3.
全屏模式：SurfaceView 可以覆盖在其他视图之上，实现全屏显示。
4.
低延迟：SurfaceView 可以减少帧率和延迟，提高用户体验。
5.
支持双缓冲：SurfaceView 内部实现了双缓冲技术，可以减少闪烁和撕裂现象。

那就使用SurfaceView实现倒计时功能。


上图是基于SurfaceView实现的倒计时功能。首先create一个SurfaceView，然后获取对应的Surface Holder。
通过start()和cancel()开启或结束绘制线程。该绘制线程周期性（间隔1s）计时。在计时点通过Surface Holder获取到canvas，然后将计时信息绘制到canvas上并提交。计时结束后destroy这个SurfaceView。


```java
public void refresh(String text) {
    try {
        if (!mSurfaceHolder.getSurface().isValid()) {
            LogCatLog.w(TAG, "refresh: surface is invalid");
            return;
        }
        Canvas canvas = null;
        try {
            canvas = mSurfaceHolder.lockCanvas();
            if (canvas != null) {
                LogCatLog.d(TAG, "refresh: text=" + text);
                canvas.drawColor(Color.TRANSPARENT, PorterDuff.Mode.CLEAR);
                canvas.drawText(text, viewWidth / 2, mBaseline, mTextPain);
            }
        } catch (Throwable t) {
            LogCatLog.e(TAG, t);
        } finally {
            if (canvas != null) {
                //释放canvas对象并提交画布
                mSurfaceHolder.unlockCanvasAndPost(canvas);
            }
        }
    } catch (Throwable t) {
        LogCatLog.e(TAG, t);
    }
}
```
## Links
- [Operating Systems](/docs/CS/OS/OS.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)