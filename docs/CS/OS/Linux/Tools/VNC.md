## Introduction


```shell
sudo apt install gnome-panel gnome-settings-daemon metacity nautilus gnome-terminal ubuntu-desktop ubuntu-gnome-desktop tigervnc-standalone-server
```

```shell
cp ~/.vnc/xstartup ~/.vnc/xstartup.bak
vim ~/.vnc/xstartup
```


```
#!/bin/sh
export XKL_XMODMAP_DISABLE=1
export XDG_CURRENT_DESKTOP="GNOME-Flashback:GNOME"
export XDG_MENU_PREFIX="gnome-flashback-"
gnome-session --session=gnome-flashback-metacity --disable-acceleration-check
```



```shell
tigervncserver -xstartup /usr/bin/gnome-session -localhost no
```


## Links

