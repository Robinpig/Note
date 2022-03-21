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
    re [shape="polygon" label="Result Set"]
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



## PreparStatement
It's safety to use #{} replace \${}


## Links
- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [MyBatis](/docs/CS/Java/MyBatis/MyBatis.md)