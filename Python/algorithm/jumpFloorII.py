"""
一只青蛙一次可以跳上1级台阶，也可以跳上2级……它也可以跳上n级。求该青蛙跳上一个n级的台阶总共有多少种跳法。
n<=0不纳入condition
贪心算法 动态规划问题
"""


def recursive_solution(target):
    """
    1.传统递归法
    :param target:
    :return:
    """
    if 1 == target:
        return 1
    if 2 == target:
        return 2
    return recursive_solution(target - 1) + recursive_solution(target - 2)


def recycle_solution(target):
    """
    2.双重循环,略
    :param target:
    :return:
    """



def solution(target):
    """
    3.数学推导
    每加一个台阶，数量会翻倍，为等比数列，2^(n-1)
    """
    return 1 << (target - 1)
