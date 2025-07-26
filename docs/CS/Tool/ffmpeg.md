## Introduction


## Install


<!-- tabs:start -->

##### **brew**

```shell
brew install ffmpeg
```

##### **compile**

依赖安装

```shell
brew install fdk-aac
brew install x264
```


```shell
git clone git://source.ffmpeg.org/ffmpeg.git
git checkout remotes/origin/release/xxx


./configure --prefix=/usr/local/ffmpeg \
--enable-gpl \
--enable-version3 \
--enable-nonfree \
--enable-postproc \
--enable-libass \
--enable-libcelt \
--enable-libfdk-aac \
--enable-libfreetype \
--enable-libmp3lame \
--enable-libopencore-amrnb \
--enable-libopencore-amrwb \
--enable-libopenjpeg \
--enable-openssl \
--enable-libopus \
--enable-libspeex \
--enable-libtheora \
--enable-libvorbis \
--enable-libvpx \
--enable-libx264 \
--enable-libxvid \
--disable-static \
--enable-shared

make && sudo make install
```
<!-- tabs:end -->

验证


```shell

ffplay http://example.com/live/stream.m3u8

```






## Links
