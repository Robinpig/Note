## accept

```c
// net/socket.c
SYSCALL_DEFINE4(accept4, int, fd, struct sockaddr __user *, upeer_sockaddr,
		int __user *, upeer_addrlen, int, flags)
{
	return __sys_accept4(fd, upeer_sockaddr, upeer_addrlen, flags);
}
```

For accept, we attempt to create a new socket, set up the link with the client, wake up the client, then return the new connected fd. We collect the address of the connector in kernel space and move it to user at the very end. This is unclean because we open the socket then return an error.

1003.1g adds the ability to `recvmsg()` to query connection pending status to recvmsg. We need to add that support in a way thats clean when we restructure accept also.

1. do_accept
2. fd_install

```c

int __sys_accept4(int fd, struct sockaddr __user *upeer_sockaddr,
		  int __user *upeer_addrlen, int flags)
{
	int ret = -EBADF;
	struct fd f;

	f = fdget(fd);
	if (f.file) {
		ret = __sys_accept4_file(f.file, 0, upeer_sockaddr,
						upeer_addrlen, flags,
						rlimit(RLIMIT_NOFILE));
		fdput(f);
	}

	return ret;
}


int __sys_accept4_file(struct file *file, unsigned file_flags,
		       struct sockaddr __user *upeer_sockaddr,
		       int __user *upeer_addrlen, int flags,
		       unsigned long nofile)
{
	struct file *newfile;
	int newfd;

	newfile = do_accept(file, file_flags, upeer_sockaddr, upeer_addrlen,
			    flags);

	fd_install(newfd, newfile);	/* 	install newfile */
	return newfd;
}
```

### do_accept


1. get listen sock from file
2. [sock_alloc]()
3. copy type and ops from listen socket
3. [alloc_file]() for newsock
3. call `inet_accept`

```c

struct file *do_accept(struct file *file, unsigned file_flags,
		       struct sockaddr __user *upeer_sockaddr,
		       int __user *upeer_addrlen, int flags)
{
	struct socket *sock, *newsock;
	struct file *newfile;
	int err, len;
	struct sockaddr_storage address;

	sock = sock_from_file(file);

	newsock = sock_alloc();

	newsock->type = sock->type;
	newsock->ops = sock->ops;


	newfile = sock_alloc_file(newsock, flags, sock->sk->sk_prot_creator->name);

	err = sock->ops->accept(sock, newsock, sock->file->f_flags | file_flags,
					false);
	...
    
	/* File flags are not inherited via accept() unlike another OSes. */
	return newfile;
}
```



#### sock_alloc_file

Bind a &socket to a &file

```c

struct file *sock_alloc_file(struct socket *sock, int flags, const char *dname)
{
	struct file *file;

	file = alloc_file_pseudo(SOCK_INODE(sock), sock_mnt, dname,
				O_RDWR | (flags & O_NONBLOCK),
				&socket_file_ops);
	

	sock->file = file;
	file->private_data = sock;
	stream_open(SOCK_INODE(sock), file);
	return file;
}
```

#### alloc_file

```c
// fs/file_table.c
struct file *alloc_file_pseudo(struct inode *inode, struct vfsmount *mnt,
				const char *name, int flags,
				const struct file_operations *fops)
{
	...
	file = alloc_file(&path, flags, fops);
	return file;
}

/* alloc_file - allocate and initialize a 'struct file' 	*/
static struct file *alloc_file(const struct path *path, int flags,
		const struct file_operations *fop)
{
	struct file *file;

	file = alloc_empty_file(flags, current_cred());
	...
	file->f_op = fop;
	return file;
}
```



#### file_operations

Socket files have a set of 'special' operations as well as the generic file ones. These don't appear in the operation structures but are done directly via the socketcall() multiplexor.

```c
// net/socket.c
static const struct file_operations socket_file_ops = {
	.owner =	THIS_MODULE,
	.llseek =	no_llseek,
	.read_iter =	sock_read_iter,
	.write_iter =	sock_write_iter,
	.poll =		sock_poll, 	/** sock_poll 	*/
	.unlocked_ioctl = sock_ioctl,
#ifdef CONFIG_COMPAT
	.compat_ioctl = compat_sock_ioctl,
#endif
	.mmap =		sock_mmap,
	.release =	sock_close,
	.fasync =	sock_fasync,
	.sendpage =	sock_sendpage,
	.splice_write = generic_splice_sendpage,
	.splice_read =	sock_splice_read,
	.show_fdinfo =	sock_show_fdinfo,
};
```

### fd_install

Install a file pointer in the fd array.

The VFS is full of places where we drop the files lock between setting the open_fds bitmap and installing the file in the file array.  At any such point, we are vulnerable to a dup2() race installing a file in the array before us.  We need to detect this and fput() the struct file we are about to overwrite in this case.

It should never happen - if we allow dup2() do it, _really_ bad things will follow.

This consumes the "file" refcount, so callers should treat it as if they had called fput(file).



```c
void fd_install(unsigned int fd, struct file *file)
{
	struct files_struct *files = current->files;
	struct fdtable *fdt;

  ...
	fdt = files_fdtable(files);	
	rcu_assign_pointer(fdt->fd[fd], file);
	
}
```





TODO:

> 127.0.0.1 本机网络IO不需要经过网卡， 不经过Ring Buffer 直接把skb传送给协议接收栈， 可以通过BPF绕过内核协议栈，减少开销（Istio的sidecar代理与本地进程通信）

## mmap

## sendfile

## References

1. [打破砂锅挖到底—— Epoll 多路复用是如何转起来的？](https://mp.weixin.qq.com/s/Py2TE9CdQ92fGLpg-SEj_g)