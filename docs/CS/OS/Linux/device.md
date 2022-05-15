

### net_device

struct net_device - The DEVICE structure.

Actually, this whole structure is a big mistake.  It mixes I/O data with strictly "high-level" data, and it has to know about almost every data structure used in the INET module.


```c
// linux/netdevice.h

```


register_netdevice	- register a network device


Take a completed network device structure and add it to the kernel interfaces. 
A %NETDEV_REGISTER message is sent to the netdev notifier chain. 0 is returned on success. A negative errno code is returned on a failure to set up the device, or if the name is a duplicate.

Callers must hold the rtnl semaphore. You may want register_netdev() instead of this.

BUGS:
The locking appears insufficient to guarantee two parallel registers will not get the same name.
















## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)






