


pthread_create

```c
#include <pthread.h>
int pthread_create( pthread_t * thread,
                    const pthread_attr_t * attr,
                    void * (*start_routine)(void*),
                    void * arg);
```
There are four arguments: thread, attr, start routine, and arg. 
The first, thread, is a pointer to a structure of type pthread t; we’ll use this structure to interact with this thread, and thus we need to pass it to pthread create() in order to initialize it.


The second argument, attr, is used to specify any attributes this thread might have. Some examples include setting the stack size or perhaps information about the scheduling priority of the thread. 
An attribute is initialized with a separate call to pthread attr init(); see the manual page for details. 
However, in most cases, the defaults will be fine; we will simply pass the value NULL in.

The third argument is the most complex, but is really just asking: which function should this thread start running in? In C, we call this a function pointer, and this one tells us the following is expected: a function name
(start routine), which is passed a single argument of type void * (as indicated in the parentheses after start routine), and which returns a value of type void * (i.e., a void pointer).

Finally, the fourth argument, arg, is exactly the argument to be passed to the function where the thread begins execution.





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

To use a condition variable, one has to in addition have a lock that is associated with this condition.

A typical usage looks like this:

```c
pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
pthread_cond_t cond = PTHREAD_COND_INITIALIZER;

Pthread_mutex_lock(&lock);
while (ready == 0)
    Pthread_cond_wait(&cond, &lock);
Pthread_mutex_unlock(&lock);
```


