# 二维数组中的查找
class Solution:
    def Find(self, target, array):
        rows = len(array) - 1
        cols = len(array[0]) - 1
        i = rows
        j = 0
        while j <= cols and i >= 0:
            if target < array[i][j]:
                i -= 1
            elif target > array[i][j]:
                j += 1
            else:
                return True
        return False

#替换空格
class Solution:
    # s 源字符串
    def replaceSpace(self, s):
        s_ = ''
        for j in s:
            if j == ' ':
                s_ = s_ + '%20'
            else:
                s_ = s_ + j
        return s_

#从尾到头打印链表
class Solution:
    def printListFromTailToHead(self, listNode):
        if not listNode:
            return []
        p = listNode
        stack = []
        res = []
        while p:
            stack.append(p.val)
            p = p.next
        for i in range(len(stack)-1,-1,-1):
             res.append(stack[i])
        return res