

pthread_create

```c
#include <pthread.h>
int pthread_create( pthread_t * thread,
                    const pthread_attr_t * attr,
                    void * (*start_routine)(void*),
                    void * arg);
```

共有四个参数：thread、attr、start routine 和 arg。
第一个参数 thread 是指向 `pthread_t` 类型结构体的指针；我们使用这个结构与线程进行交互，因此需要将其传递给 `pthread_create()` 以完成初始化。

第二个参数 attr 用于指定线程可能具有的任何属性。一些示例包括设置栈大小或线程的调度优先级信息。
属性通过单独调用 `pthread_attr_init()` 进行初始化；详情请参见手册页。
然而，在大多数情况下，默认值就足够了；我们只需传入 `NULL` 即可。

第三个参数最为复杂，但它实际上只是问：这个线程应该从哪个函数开始运行？在 C 语言中，我们称之为函数指针，这个指针告诉我们期望如下内容：一个函数名（start routine），该函数接收一个 `void *` 类型的参数（如 start routine 后的括号中所示），并返回一个 `void *` 类型的值（即 void 指针）。

最后，第四个参数 arg 正是要传递给线程开始执行时所运行函数的参数。

mmap

mprotect

clone

## Mutex

```c
// Use this to keep your code clean but check for failures
// Only use if exiting program is OK upon failure
void Pthread_mutex_lock(pthread_mutex_t *mutex) {
    int rc = pthread_mutex_lock(mutex);
    assert(rc == 0);
}
```

tryLock

```c
int pthread_mutex_trylock(pthread_mutex_t *mutex);
int pthread_mutex_timedlock(pthread_mutex_t *mutex,
                            struct timespec *abs_timeout);
```

### Condition Variable

```c
int pthread_cond_wait(pthread_cond_t *cond, pthread_mutex_t *mutex);
int pthread_cond_signal(pthread_cond_t *cond);
```

要使用条件变量，还需要有一个与该条件关联的锁。

典型用法如下：

```c
pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
pthread_cond_t cond = PTHREAD_COND_INITIALIZER;

Pthread_mutex_lock(&lock);
while (ready == 0)
    Pthread_cond_wait(&cond, &lock);
Pthread_mutex_unlock(&lock);
```

## Links

- [processes](/docs/CS/OS/Linux/proc/process.md)
