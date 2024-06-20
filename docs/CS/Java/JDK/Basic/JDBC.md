## Introduction

```dot
strict digraph {

    source [shape="polygon" label="DataSource"]
    conn [shape="polygon" label="Connection"]
    source -> conn [label="getConnection"]
    st [shape="polygon" label="Statement"]
    pr [shape="polygon" label="PrepareStatement"]
    ca [shape="polygon" label="CallableStatement"]
    {rank="same"; st;pr;ca;}
    data [shape="polygon" label="Data types"]
    re [shape="polygon" label="ResultSet"]
    re -> data [label="getXXX"]
    st -> pr [label="subClass"]
    pr -> ca [label="subClass"]
    conn -> st [label="createStatement"]
    conn -> pr [label="prepareStatement"]
    conn -> ca [label="prepareCall"]
    data -> pr [label="Input to PrepareStatement"]
    data -> ca [label="Input/Output of CallableStatement" dir = both]
    st -> re [label="executeQuery"]
    pr -> re [label="executeQuery"]
    
    ca -> re [label="executeQuery \n getMoreResults/getResultSet"]
}
```

Connection isClose() or isValid()



## PrepareStatement

提前生成执行计划
- 性能稍微好一点
- 执行引擎按照执行计划执行 可以防SQL注入

It's safety to use #{} replace \${}


## Links
- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [MyBatis](/docs/CS/Java/MyBatis/MyBatis.md)