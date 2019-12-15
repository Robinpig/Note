# 广度优先搜索算法 解决无权图最短路径
# Breadth First Search
# 距离     前驱顶点    颜色
from pythonds import Queue


def bfs(g, start):
    start.setDistance(0)
    start.setPred(None)
    vertQueue = Queue()
    vertQueue.enqueue(start)
    while (vertQueue.size() > 0):
        currentVert = vertQueue.dequeue()
        for nbr in currentVert.getConnecttions():
            if (nbr.getColor() == 'white'):
                nbr.setColor('grey')
                nbr.setDistance(currentVert.getDistance() + 1)
                nbr.setPred(currentVert)
                vertQueue.enqueue(nbr)
        currentVert.setColor('black')
