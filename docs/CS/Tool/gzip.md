## Introduction


https://datatracker.ietf.org/doc/html/rfc1952#page-5

gzip

Each member has the following structure:

         +---+---+---+---+---+---+---+---+---+---+
         |ID1|ID2|CM |FLG|     MTIME     |XFL|OS | (more-->)

第5-8个字节为文档的修改时间（timestamp），使用小端模式编码

gzip提供功能设置修改时间为0

gzip -n -c swagger.yaml | xxd -p -c 4 | sed -n '2p'


## Links

