"""
Given an array of integers, return indices of the two numbers
such that they add up to a specific target.
You may assume that each input would have exactly one solution,
and you may not use the same element twice.
Example:
    Given nums = [2, 7, 11, 15], target = 9,
    Because nums[0] + nums[1] = 2 + 7 = 9,
    return (0, 1)
"""


def two_sum(array, target):
    """
    enumerate() 函数用于将一个可遍历的数据对象
    (如列表、元组或字符串)组合为一个索引序列，
    同时列出数据和数据下标，一般用在 for 循环当中。
    """
    dic = {}
    for index, element in enumerate(array):
        if element in dic:
            # 当存在element为此前存在时，返回之前索引和当前索引
            return dic[element], index
        else:
            # 添加到dic存储<target-element，index>
            dic[target - element] = index
    return None


if __name__ == '__main__':
    array = [2, 4, 5, 6, 7]
    print(two_sum(array, 8))
