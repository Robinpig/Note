



```c
// linux/include/linux/list.h

/**
 * list_add - add a new entry
 * @new: new entry to be added
 * @head: list head to add it after
 *
 * Insert a new entry after the specified head.
 * This is good for implementing stacks.
 */
static inline void list_add(struct list_head *new, struct list_head *head)
{
       __list_add(new, head, head->next);
}


/**
 * list_add_tail - add a new entry
 * @new: new entry to be added
 * @head: list head to add it before
 *
 * Insert a new entry before the specified head.
 * This is useful for implementing queues.
 */
static inline void list_add_tail(struct list_head *new, struct list_head *head)
{
       __list_add(new, head->prev, head);
}
```



```c
// linux/include/linux/list.h
/*
 * Insert a new entry between two known consecutive entries.
 *
 * This is only for internal list manipulation where we know
 * the prev/next entries already!
 */
static inline void __list_add(struct list_head *new,
                           struct list_head *prev,
                           struct list_head *next)
{
       if (!__list_add_valid(new, prev, next))
              return;

       next->prev = new;
       new->next = next;
       new->prev = prev;
       WRITE_ONCE(prev->next, new);
}
```



### foreach



```c
/**
 * list_for_each       -      iterate over a list
 * @pos:       the &struct list_head to use as a loop cursor.
 * @head:      the head for your list.
 */
#define list_for_each(pos, head) \
       for (pos = (head)->next; pos != (head); pos = pos->next)
```

```c
/**
 * list_entry - get the struct for this entry
 * @ptr:       the &struct list_head pointer.
 * @type:      the type of the struct this is embedded in.
 * @member:    the name of the list_head within the struct.
 */
#define list_entry(ptr, type, member) \
       container_of(ptr, type, member)
```