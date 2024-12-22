## Introduction

[Kong](https://docs.konghq.com/gateway/latest/)是一个在Nginx中运行的Lua应用程序，并且可以通过lua-nginx模块实现。Kong不是用这个模块编译Nginx，而是与OpenResty一起分发，OpenResty已经包含了lua-nginx-module。OpenResty不是Nginx的分支，而是一组扩展其功能的模块



```yml
docker pull kong:2.0

docker pull postgres:9.6
mkdir -p /opt/postgres/data
docker run -d --name postgres \
	-e POSTGRES_PASSWORD=password \
	-p 5432:5432 \version: '3'

services:

  kong-database:
    image: postgres:9.6
    container_name: kong-database
    ports:
      - 5432:5432
    environment:
      - POSTGRES_USER=kong
      - POSTGRES_DB=kong
      - POSTGRES_PASSWORD=kong
    volumes:
      - "/opt/kong-db-data-postgres:/var/lib/postgresql/data"

  kong-migrations:
    image: kong:2
    environment:
      - KONG_DATABASE=postgres
      - KONG_PG_HOST=kong-database
      - KONG_PG_USER=kong
      - KONG_PG_PASSWORD=kong
    command: kong migrations bootstrap
    restart: on-failure
    depends_on:
      - kong-database

  kong:
    image: kong:2
    container_name: kong
    environment:
      - KONG_DATABASE=postgres
      - KONG_PG_HOST=kong-database
      - KONG_PG_USER=kong
      - KONG_PG_PASSWORD=kong
      - KONG_PROXY_ACCESS_LOG=/dev/stdout
      - KONG_ADMIN_ACCESS_LOG=/dev/stdout
      - KONG_PROXY_ERROR_LOG=/dev/stderr
      - KONG_ADMIN_ERROR_LOG=/dev/stderr
      - KONG_ADMIN_LISTEN=0.0.0.0:8001, 0.0.0.0:8444 ssl
    restart: on-failure
    ports:
      - 8000:8000
      - 8443:8443
      - 8001:8001
      - 8444:8444
    links:
      - kong-database:kong-database
    depends_on:
      - kong-migrations

  konga:
    image: pantsel/konga:0.14.9
    ports:
      - 1337:1337
    links:
      - kong:kong
    container_name: konga
    environment:
      - NODE_ENV=production
	-v /home/data/postgres/data:/var/lib/postgresql/data \
	postgres:9.6
```





## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)