## Introduction

A  *graph G = * ( *V, E* ) consists of a set of  *vertices* , *V,* and a set of  *edges* ,  *E* . Each edge is a pair ( *v,w* ), where *v,w *!*V* .
Edges are sometimes referred to as  *arcs* . If the pair is ordered, then the graph is  *directed* . Directed graphs are sometimes referred to as  *digraphs* .
Vertex *w* is *adjacent* to *v* if and only if ( *v,w* ) !*E* .
In an undirected graph with edge ( *v,w* ), and hence ( *w,v* ), *w* is adjacent to *v* and *v* is adjacent to  *w* . Sometimes an edge has a third component, known as either a *weight* or a  *cost* .

A *path* in a graph is a sequence of verices *w*~1~ , *w*~2~ , *w*~3~ , . . . , *w~n~* such that ( *w~i~* ,  *w~i~* + *i* ) *E* for 1 !*i*&lt;*n* .
The *length* of such a path is the number of edges on the path, which is equal to *n* - 1.
We allow a path from a vertex to itself; if this path contains no edges, then the path lenght is 0. This is a convenient way to define an otherwise special case.
If the graph contains an edge ( *v,v* ) from a vertex to itself, then the path  *v* , *v* is sometimes referred to as a  *loop* .
The graphs we will consider will generally be loopless. A *simple* path is a path such that all vertices are distinct, except that the first and last could be the same.

A *cycle* in a directed graph is a path of length at least 1 such that *w*~1~ =  *w~n~* ; this cycle is simple if the path is simple. For undirected graphs, we require that the edges be distinct.
The logic of these requirements is that the path  *u* , *v, u* in an undirected graph should not be considered a cycle, because ( *u* ,  *v* ) and ( *v* ,  *u* ) are the same edge.
In a directed graph, these are different edges, so it makes sense to call this a cycle. A directed graph is *acyclic* if it has no cycles.
A directed acyclic graph is sometimes referred to by its abbreviation,  *DAG* .

An undirected graph is *connected* if there is a path from every vertex to every other vertex.
A directed graph with this property is called  *strongly connected* .
If a directed graph is not strongly connected, but the underlying graph (without direction to the arcs) is connected, then the graph is said to be  *weakly connected* .
A *complete graph* is a graph in which there is an edge between every pair of vertices.

## Representation of Graphs

One simple way to represent a graph is to use a two-dimensional array. This is known as an *adjacency* *matrix* representation.

If the graph is  *sparse* , a better solution is an *adjacency list* representation. For each vertex, we keep a list of all adjacent vertices. The space requirement is then  *O|E| + |* V|).

## Topological Sort

## Shortest-Path Algorithms

### Unweighted Shortest Paths

### Dijkstra's Algorithm

## Minimum Spanning Tree

### Prim's Algorithm

### Kruskal's Algorithm





## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [algorithm analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)
