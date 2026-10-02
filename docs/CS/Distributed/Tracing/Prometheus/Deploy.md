


```


                        ┌─────────────┐
                        │   用户访问   │
                        └──────┬──────┘
                               │
                    ┌──────────▼──────────┐
                    │  Nginx 负载均衡      │
                    │  (Node3:80/443)     │
                    └──┬──────────────┬───┘
                       │              │
              ┌────────▼──┐    ┌──────▼────────┐
              │ Grafana-1  │    │  Grafana-2     │
              │ (Node1)    │    │  (Node2)       │
              └────────┬──┘    └──────┬─────────┘
                       │              │
              ┌────────▼──┐    ┌──────▼─────────┐
              │Prometheus-1│    │Prometheus-2    │
              │ (Node1)    │    │ (Node2)        │
              └────────┬──┘    └──────┬─────────┘
                       │              │
         ┌─────────────▼──────────────▼─────────────┐
         │           Alertmanager 集群               │
         │  am-1(Node1)  am-2(Node2)  am-3(Node3)   │
         └──────────────────────────────────────────┘
                       │
         ┌─────────────▼──────────────┐
         │  OceanBase MySQL 租户      │
         │  (已有集群，外部部署)       │
         └────────────────────────────┘

```




| 节点 | IP（示例） | 部署组件 |
|------|-----------|---------|
| Node1 | 192.168.1.11 | Prometheus-1, Alertmanager-1, Grafana-1 |
| Node2 | 192.168.1.12 | Prometheus-2, Alertmanager-2, Grafana-2 |
| Node3 | 192.168.1.13 | Alertmanager-3, Nginx |




-- 连接到 OceanBase MySQL 租户（通过 OBProxy 或直连）
-- 创建 Grafana 专用数据库
CREATE DATABASE grafana CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;

-- 创建 Grafana 专用用户
CREATE USER 'grafana'@'%' IDENTIFIED BY 'your_secure_password';

-- 授权（Grafana 需要对库有完整读写权限来管理内部表）
GRANT ALL PRIVILEGES ON grafana.* TO 'grafana'@'%';
FLUSH PRIVILEGES;


Node1 和 Node2 共用 grafana/grafana.ini


[server]
protocol = http
http_port = 3000
instance_name = ${GRAFANA_INSTANCE_NAME}

[database]
type = mysql
host = 192.168.1.100:2883
name = grafana
user = grafana
password = your_secure_password
max_open_conn = 100
max_idle_conn = 50
conn_max_lifetime = 14400

[session]
provider = mysql
provider_config = grafana:your_secure_password@tcp(192.168.1.100:2883)/grafana?charset=utf8mb4&parseTime=true&loc=Local

[remote_cache]
type = mysql
connstr = grafana:your_secure_password@tcp(192.168.1.100:2883)/grafana?charset=utf8mb4&parseTime=true&loc=Local

[unified_alerting]
enabled = true
ha_listen_address = 0.0.0.0:9094
ha_peers = 192.168.1.11:9094,192.168.1.12:9094
ha_advertise_address = ${SELF_IP}:9094
ha_peer_timeout = 15s

[security]
admin_user = admin
admin_password = your_grafana_admin_password


关键说明：
type = mysql：Grafana 原生支持 MySQL 协议，OceanBase MySQL 租户完全兼容
host 填写 OceanBase OBProxy 的地址和端口（默认 2883），也可以直连 OBServer（默认 2881）
connstr 使用 Go 的 MySQL DSN 格式，parseTime=true 是 Grafana 要求的，确保时间字段正确解析
charset=utf8mb4 确保中文等字符正确存储
Docker Compose 编排文件
Node1 (192.168.1.11) 和 Node2 (192.168.1.12)

version: '3.8'

services:
  prometheus:
    image: prom/prometheus:v2.53.0
    container_name: prometheus
    restart: always
    network_mode: host
    user: "0:0"
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
      - ./prometheus/data:/prometheus
      - ./prometheus/rules:/etc/prometheus/rules
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'
      - '--web.enable-lifecycle'
      - '--web.enable-admin-api'

  alertmanager:
    image: prom/alertmanager:v0.27.0
    container_name: alertmanager
    restart: always
    network_mode: host
    volumes:
      - ./alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml
      - ./alertmanager/data:/alertmanager
    command:
      - '--config.file=/etc/alertmanager/alertmanager.yml'
      - '--storage.path=/alertmanager'
      - '--cluster.listen-address=0.0.0.0:9094'
      - '--cluster.peer=192.168.1.11:9094'
      - '--cluster.peer=192.168.1.12:9094'
      - '--cluster.peer=192.168.1.13:9094'

  grafana:
    image: grafana/grafana:11.1.0
    container_name: grafana
    restart: always
    network_mode: host
    volumes:
      - ./grafana/grafana.ini:/etc/grafana/grafana.ini
      - ./grafana/data:/var/lib/grafana
    environment:
      - GF_INSTALL_PLUGINS=grafana-clock-panel,grafana-piechart-panel
    depends_on:
      - prometheus

  node-exporter:
    image: prom/node-exporter:v1.8.1
    container_name: node-exporter
    restart: always
    network_mode: host
    pid: host
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
