"""
给定一个数组和滑动窗口的大小，
找出所有滑动窗口里数值的最大值。
例如，如果输入数组{2,3,4,2,6,2,5,1}及滑动窗口的大小3，
那么一共存在6个滑动窗口，他们的最大值分别为{4,4,6,6,6,5}；
针对数组{2,3,4,2,6,2,5,1}的滑动窗口有以下6个：
{[2,3,4],2,6,2,5,1}，
{2,[3,4,2],6,2,5,1}，
{2,3,[4,2,6],2,5,1}，
{2,3,4,[2,6,2],5,1}，
{2,3,4,2,[6,2,5],1}，
{2,3,4,2,6,[2,5,1]}。
"""
from pygments.util import xrange


def max_sliding_window(nums, k):
    """
    max()获取nums在窗口内最大值
    :param nums:
    :param k:
    :return:
    """
    if k <= 0:
        return []
    res = []
    for i in xrange(0, len(nums) - k + 1):
        res.append(max(nums[i:i + k]))
    return res


def max_in_windows(num, size):
    """
    使用一个队列，头部为最大值，
    新入队的元素从队列尾部往前比较，
    若大于等于存在与队列的值则原有值出栈
    当队列中数超过size，最大值出队
    :param num:
    :param size:
    :return:
    """
    i = 0
    queue = []
    res = []
    while size > 0 and i < len(num):
        # i表示当前窗口中的最后一个数字下标
        # 判断queue[0]是否还在当前窗口中
        if len(queue) > 0 and i - size + 1 > queue[0]:
            queue.pop(0)
        # 当队列不为0时，从队列尾部往前比较，
        while len(queue) > 0 and num[queue[-1]] <= num[i]:
            queue.pop()
        queue.append(i)
        # i=size-1时，第一个窗口建立完成，开始记录最大下标
        if i >= size - 1:
            res.append(num[queue[0]])
        i += 1
    return res


if __name__ == '__main__':
    num = [3, 9, 4, 56, 6, 7, 8, 8, 8, 6, 3, 44, 2, 1]
    size = 7
    print(max_in_windows(num, size))
    print(max_sliding_window(num, size))
