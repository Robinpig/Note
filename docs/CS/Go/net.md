## Introduction




```go
package main

import (
    "fmt"
    "net/http"
    "encoding/json"
)

var sum = 0

func main() {
    http.HandleFunc("/users", listUser)
    http.ListenAndServe(":8087", nil)

}

func listUser(w http.ResponseWriter, r *http.Request) {
    users := make(map[string]int)
    users["zhangsan"] = 1
    users["lisi"] = 2
    users["wangwu"] = 3

    switch r.Method {
    case "GET":
        users, err := json.Marshal(users)
        if err != nil {
            w.WriteHeader(http.StatusInternalServerError)
            fmt.Fprint(w, "{\"message\": \""+err.Error()+"\"}")
        } else {
            w.WriteHeader(http.StatusOK)
            w.Write(users)
        }

    default:
        w.WriteHeader(http.StatusNotFound)
        fmt.Fprint(w, "{\"message\": \"not found\"}")
    }
}
```

gin

虽然 Go 语言自带的 net/http 包，可以比较容易地创建 HTTP 服务，但是它也有很多不足：
- 不能单独地对请求方法（POST、GET 等）注册特定的处理函数；
- 不支持 Path 变量参数；
- 不能自动对 Path 进行校准；
- 性能一般；
- 扩展性不足；
- ……

基于以上这些不足，出现了很多 Golang Web 框架，如 Mux，Gin、Fiber 等
a

安装gin
```shell
go get -u github.com/gin-gonic/gin
```

```go
package main

import (
    "fmt"
    "github.com/gin-gonic/gin"
)

func main() { 
    r := gin.Default()
    r.GET("/users", listUser)
    r.Run(":8087")

}

func listUser(c *gin.Context) {
    users := make(map[string]int)
    users["zhangsan"] = 1
    users["lisi"] = 2
    users["wangwu"] = 3
    c.JSON(200, users)

}
```