"""
实现一个算法，确定一个长度为n字符串 s 的所有字符是否全都不同。
存在0-n/2个字符可能有重复
"""


def is_unique(astr: str) -> bool:
    """
    使用set将字符存入，若len小于原字符串则返回false
    0(n)
    :param astr:
    :return:
    """
    sets = set(astr)
    return len(sets) == len(astr)


"""
字符串转换成char array
两层遍历，O(n^2)
"""

"""
遍历char数组存入hashTable，O(n)
"""

if __name__ == '__main__':
    print(is_unique("afsdffaf"))
