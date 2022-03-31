## Introduction

For TCP/IP networks, the Address Resolution Protocol (ARP) [RFC0826] provides a dynamic mapping between IPv4 addresses and the hardware addresses used by various network technologies. 
ARP is used with IPv4 only; IPv6 uses the Neighbor Discovery Protocol, which is incorporated into ICMPv6.


> [!Note]
> 
> A related protocol that provides the reverse mapping from ARP, called RARP, was used by systems lacking a disk drive (normally diskless workstations or X terminals). 
> It is rarely used today and requires manual configuration by the system administrator. 
> See [RFC0903] for details.


ARP sends an Ethernet frame called an ARP request to every host on the shared link-layer segment. This is called a *link-layer broadcast*.



## ARP Cache

Essential to the efficient operation of ARP is the maintenance of an ARP cache (or table) on each host and router. 
This cache maintains the recent mappings from network-layer addresses to hardware addresses for each interface that uses address resolution. 
When IPv4 addresses are mapped to hardware addresses, the normal expiration time of an entry in the cache is 20 minutes from the time the entry was created, as described in [RFC1122].

```shell
arp -a
```

### Cache Timeout


## Proxy ARP


## Links

- [Computer Network](/docs/CS/CN/CN.md)