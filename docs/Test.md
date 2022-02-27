
```mermaid
graph LR
    A --- B
    B-->C[fa:fa-ban forbidden]
    B-->D(fa:fa-spinner);
```

<img src='https://g.gravizo.com/svg?
digraph G {
main -> parse -> execute;
main -> init;
main -> cleanup;
execute -> make_string;
execute -> printf
init -> make_string;
main -> printf;
execute -> compare;
}
'/>


```dot
graph G {
compound=true;
graph [pad="0.8",ranksep="0.2 equally",nodesep="0.1"];
splines=false;
subgraph cluster_basic {
color=none;
node [shape="plain"];
node_start [label="Front-end",fontsize=24];
node_ltb [label="Learn the Basics"]
node_start -- node_ltb;
node [shape="box",style="filled",fillcolor="#FFFF41",width=3];
HTML -- CSS -- "Basics of JavaScript" [style=invis];
"Basics of JavaScript" -- "Package Managers" -- "CSS Pre-processor" -- "etc.";
node_ltb -- HTML [lhead= cluster_basic];
}
subgraph cluster_html_boj {
color=none;
blank1 [label="",color=none];
node [shape="box",style="filled",fillcolor="#FFE59F",width=2.8];
ltb0 [label="Learn the basics"]
HTML -- {ltb0, "Writing Semantic", "Basic SEO", "Accessibility"} [style="dashed",constraint=false];
ltb0 -- "Writing Semantic" -- "Basic SEO" -- "Accessibility" -- blank1 -- boj1 [style=invis];
boj1 [label="Syntax and Basic Constructs"];
boj2 [label="Learn DOM Manipulation"];
boj3 [label="Learn Fetch API/Ajax(XHR)"];
boj4 [label="ES6+ and modular JavaScript"];
boj5 [label="Understand the concepts
Hosting, Event Bubbling, Scope
Prototype, Shadow DOM, strict,
how browsers work, DNS, HTTP"];
"Basics of JavaScript" -- {boj1, boj2, boj3, boj4, boj5} [style="dashed"]
boj1 -- boj2 -- boj3 -- boj4 -- boj5 [style=invis];
}
subgraph cluster_css_pm {
color=none;
blank2 [label="",color=none];
node [shape="box",style="filled",fillcolor="#FFE59F",width=1.8];
ltb1 [label="Learn the basics"]
CSS -- {ltb1, "Making Layouts", "Media Queries", "Learn CSS 3"} [style="dashed",constraint=false]
ltb1 -- "Making Layouts" -- "Media Queries" -- "Learn CSS 3" -- blank2 -- npm [style=invis];
"Package Managers" -- {npm, yarn} [style="dashed"];
npm -- yarn [style=invis];
}
}
```


<!-- tabs:start -->
#### **mermaid**

```mermaid
sequenceDiagram
    participant Alice
    participant Bob
    Alice->>John: Hello John, how are you?
    loop Healthcheck
        John->>John: Fight against hypochondria
    end
    Note right of John: Rational thoughts <br/>prevail!
    John-->>Alice: Great!
    John->>Bob: How about you?
    Bob-->>John: Jolly good!
```

#### **graphviz**

```dot
graph G {
compound=true;
graph [pad="0.8",ranksep="0.2 equally",nodesep="0.1"];
splines=false;
subgraph cluster_basic {
color=none;
node [shape="plain"];
node_start [label="Front-end",fontsize=24];
node_ltb [label="Learn the Basics"]
node_start -- node_ltb;
node [shape="box",style="filled",fillcolor="#FFFF41",width=3];
HTML -- CSS -- "Basics of JavaScript" [style=invis];
"Basics of JavaScript" -- "Package Managers" -- "CSS Pre-processor" -- "etc.";
node_ltb -- HTML [lhead= cluster_basic];
}
subgraph cluster_html_boj {
color=none;
blank1 [label="",color=none];
node [shape="box",style="filled",fillcolor="#FFE59F",width=2.8];
ltb0 [label="Learn the basics"]
HTML -- {ltb0, "Writing Semantic", "Basic SEO", "Accessibility"} [style="dashed",constraint=false];
ltb0 -- "Writing Semantic" -- "Basic SEO" -- "Accessibility" -- blank1 -- boj1 [style=invis];
boj1 [label="Syntax and Basic Constructs"];
boj2 [label="Learn DOM Manipulation"];
boj3 [label="Learn Fetch API/Ajax(XHR)"];
boj4 [label="ES6+ and modular JavaScript"];
boj5 [label="Understand the concepts
Hosting, Event Bubbling, Scope
Prototype, Shadow DOM, strict,
how browsers work, DNS, HTTP"];
"Basics of JavaScript" -- {boj1, boj2, boj3, boj4, boj5} [style="dashed"]
boj1 -- boj2 -- boj3 -- boj4 -- boj5 [style=invis];
}
subgraph cluster_css_pm {
color=none;
blank2 [label="",color=none];
node [shape="box",style="filled",fillcolor="#FFE59F",width=1.8];
ltb1 [label="Learn the basics"]
CSS -- {ltb1, "Making Layouts", "Media Queries", "Learn CSS 3"} [style="dashed",constraint=false]
ltb1 -- "Making Layouts" -- "Media Queries" -- "Learn CSS 3" -- blank2 -- npm [style=invis];
"Package Managers" -- {npm, yarn} [style="dashed"];
npm -- yarn [style=invis];
}
}
```


<!-- tabs:end -->



<img src='https://g.gravizo.com/svg?
digraph G {
main -> parse -> execute;
main -> init;
main -> cleanup;
execute -> make_string;
execute -> printf
init -> make_string;
main -> printf;
execute -> compare;
}
'/>


```sequence
participant User
User -->> User: send messages
participant WorkEventLoopGroup as we
participant Selector as se
we ->> se: selector.select()
se ->> we: OP_READ
participant NioByteUnsafe as ue
we ->> ue: NioUnsafe.read()
participant NioSocketChannel as so
ue ->> so: NioUnsafe.read()
so ->> ue: -1(EOF)
ue -->> ue: closeOnRead()
participant ChannelPipeline as pipe

```



```sequence
participant User
User -->> User: send messages
participant WorkEventLoopGroup as we
participant Selector as se
we ->> se: selector.select()
se ->> we: OP_READ
participant NioByteUnsafe as ue
we ->> ue: NioUnsafe.read()
participant NioSocketChannel as so
participant ChannelPipeline as pipe
ue ->> so: NioUnsafe.read()
so ->> ue: -1(EOF)
ue ->> pipe:pipeline.fire ChannelRead()
ue -->> ue: closeOnRead()

```







```flow
st=>start: User login
op=>operation: Operation
cond=>condition: Successful Yes or No?
e=>end: Into admin
st->op->cond
cond(yes)->e
cond(no)->op
```




```dot
digraph g{
    App[label="Application", shape=box]
    OS[label="Operating System", shape=box]
    App->OS->App
    OS->CPU->OS
    OS->Memory->OS
    OS->Devices->OS
}
```

```tex
E=mc^2
```
