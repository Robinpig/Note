## Introduction





```shell
# RPM
sudo yum install wireshark

## DEB
sudo apt-get install wireshark wireshark-qt
```

if don't have permission

```shell
cd /dev

ls -a | grep bp
# list 700

whoami
# robin

sudo chown robin:admin bp*
```





disable Relative sequence numbers

Preference -> Protocols -> TCP -> Relative sequence numbers



## Links
- [tcpdump](/docs/CS/CN/Tools/tcpdump.md)
- [Xcap](/docs/CS/CN/Tools/Xcap.md)
- [netfilter](/docs/CS/CN/Tools/netfilter.md)
