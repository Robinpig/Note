## Introduction

For TCP/IP networks, the *Address Resolution Protocol* (ARP) provides a dynamic mapping between IPv4 addresses and the hardware addresses used by various network technologies. 
ARP is used with IPv4 only; IPv6 uses the Neighbor Discovery Protocol, which is incorporated into ICMPv6.


> [!Note]
> 
> A related protocol that provides the reverse mapping from ARP, called RARP, was used by systems lacking a disk drive (normally diskless workstations or X terminals). 
> It is rarely used today and requires manual configuration by the system administrator. 



ARP sends an Ethernet frame called an ARP request to every host on the shared link-layer segment. 
This is called a *link-layer broadcast*.

Imagine a device that wants to communicate with others over the internet. 
It broadcast a packet to all the devices of the source network.
The devices of the network peel the header of the data link layer from the Protocol Data Unit (PDU) called frame and transfer the packet to the network layer (layer 3 of OSI) 
where the network ID of the packet is validated with the destination IP’s network ID of the packet and if it’s equal then it responds to the source with the MAC address of the destination, 
else the packet reaches the gateway of the network and broadcasts packet to the devices it is connected with and validates their network ID. 
The above process continues till the second last network device in the path reaches the destination where it gets validated and ARP, in turn, responds with the destination MAC address.



## ARP Cache

Essential to the efficient operation of ARP is the maintenance of an ARP cache (or table) on each host and router. 
This cache maintains the recent mappings from network-layer addresses to hardware addresses for each interface that uses address resolution. 
When IPv4 addresses are mapped to hardware addresses, the normal expiration time of an entry in the cache is 20 minutes from the time the entry was created.

```shell
arp -a
```

### Cache Timeout


## Proxy ARP

## RARP




## Links

- [Computer Network](/docs/CS/CN/CN.md)