# Nginx



## [Installing NGINX and NGINX Plus](https://docs.nginx.com/nginx/admin-guide/installing-nginx/)



NGINX反向代理后 服务端通过HttpServletRequest  request.getRemoteAddr 和 getRequestURL都是**nginx的IP 域名 协议 端口**

Fix : 

1. NGINX 将信息配置在header上往服务端传输

Nginx.conf 添加配置

```nginx
proxy_set_header Host $http_host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```



还存在问题

2. 配置服务器

![image-20210419091833417](/Users/robin/Library/Application Support/typora-user-images/image-20210419091833417.png)



## Load Balance

```nginx
# default
upstream real_serer{
	server 192.168.1.100:8000;
  server 192.168.1.100:8001;
}
```

```nginx
# weight
upstream real_serer{
	server 192.168.1.100:8000 weight=1;
  server 192.168.1.100:8001 weight=2;
}
```

```nginx
# ip_hash
upstream bakend {  
    ip_hash;  
    server 192.168.0.1:8000;  
    server 192.168.0.1:8001;  
} 
```

```nginx
# fair
upstream bakend {  
    server 192.168.0.1:8000;  
    server 192.168.0.1:8001; 
    fair;
} 
```

```nginx
# url hash
upstream bakend {  
    server 192.168.0.1:8000;  
    server 192.168.0.1:8001; 
    hash $request_uri;  
    hash_method crc32; 
} 
```

consistent hash

一致性hash就是创建出n个虚拟节点，n个虚拟节点构成一个环，从n个虚拟节点中，挑选出一些节点当成真实的upstream server节点。构成一个每次将计算得到的hash%n，得到请求分配的虚拟节点的位置c，从位置c顺时针移动，获得离c最近的真实upstream server节点

```nginx
# url hash
upstream bakend {  
  	consistent_hash $request_uri;
    server 192.168.0.1:8000;  
    server 192.168.0.1:8001; 
} 
```

fail retry

```nginx
# weight
upstream real_serer{
	server 192.168.1.100:8000 weight=1 max_fails=2 fail_timeout=60s;
  server 192.168.1.100:8001 weight=2 max_fails=2 fail_timeout=60s;
}

```



limit

limit_req_zone 

```nginx

http {
  	# leaky bucket not set burst 
    limit_req_zone $binary_remote_addr zone=one:10m rate=1r/s; 
    server {
        location /search/ {
      			# token bucket set burst
            limit_req zone=one burst=5 nodelay;
        }
}  
```



limit_conn_zone, need **ngx_http_limit_conn_module**

```nginx
  limit_conn_zone $binary_remote_addr zone=addr:10m;

  server {
      location /download/ {
              limit_conn addr 1;
      }
  }
```

白名单 黑名单

## Cache



灰度发布

根据cookie设定version来路由

~~~nginx
map $COOKIE_version $group {
	~*v1$ host1;
	~*v2$ host2;
	default default;

}
~~~

根据Ip

其它细粒度

生成缩略图 比较消耗CPU 

生成缩略图后持久到硬盘

前端Cache或者CDN

--with-http_image_filter_module

Config 配置 image_filer 



禁用IP段

log

默认输出到同一份文件

使用linux 定时任务 分割log



access_log

Log_format

Log_not_found

log_subrequest on | off

rewrite_log

error_log



Nginx -V

Add modules and  configure

**make( not make install )**

Replace nginx file

格式化log并推送到指定服务器

nginx.conf 添加配置



配置websocket



MySQL负载均衡(主主复制)

--with-stream



跨域问题



流媒体



高可用

Keepalived

VRRP 协议 Virtual Router Redundancy Protocol



对比Heartbeat Corosync 基于主机等的高可用



HTTPS

自签CA

```shell
mkdir /etc/cert

cd /etc/cert/

openssl genrsa -out yh.com.key 2048

openssl req -new -key yh.com.key -out yh.com.csr

Country Name (2 letter code) [XX]:
State or Province Name (full name) []:
Locality Name (eg, city) [Default City]:
Organization Name (eg, company) [Default Company Ltd]:
Organizational Unit Name (eg, section) []:
Common Name (eg, your name or your server's hostname) []:
Email Address []:
A challenge password []:
An optional company name []:

openssl x509 -req -days 3650 -in yh.com.csr -signkey yh.com.key -out yh.com.crt

```



Set ssl in nginx.conf

Nginx -t



四层负载均衡



