from pythonds import Graph, Vertex

g=Graph()
g.addEdge(0,1,5)
g.addEdge(0,1,5)
g.addEdge(0,1,5)
g.addEdge(0,1,5)

for i in range(6):
    g.addVertex(i)
print(g.vertList)