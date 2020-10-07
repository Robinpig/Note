import heapq
from typing import List


class heapq_solution(object):

    def __init__(self, k, nums):
        """
        :type k: int
        :type nums: List[int]
        """
        self.k = k
        self.resq = []
        for val in nums:
            if len(self.resq) < k:
                heapq.heappush(self.resq, val)
            else:
                heapq.heappushpop(self.resq, val)

    def add(self, val):
        """
        :type val: int
        :rtype: int
        """
        if len(self.resq) < self.k:
            heapq.heappush(self.resq, val)
        else:
            heapq.heappushpop(self.resq, val)
        return self.resq[0]

"""
逆向排序+二分搜索插入
时间复杂度：O（log（n））
空间复杂度：O（1）
"""
class list_solution:

    def __init__(self, k: int, nums: List[int]):
        self.nums = nums
        self.k = k
        if self.k < 0:
            self.k = 0

        self.nums = sorted(nums)[::-1]

    def add(self, val: int) -> int:
        if not self.nums:
            self.nums.append(val)
            if self.k < 2:
                return self.nums[self.k - 1]
        low = 0
        high = len(self.nums) - 1
        while low < high:
            mid = (low + high) // 2
            if self.nums[mid] < val:
                high = mid - 1
            elif self.nums[mid] > val:
                low = mid + 1
            else:
                self.nums.insert(mid, val)
                break
        if low >= high:
            if val > self.nums[low]:
                self.nums.insert(low, val)
            else:
                self.nums.insert(low + 1, val)
        if len(self.nums) >= self.k:
            return self.nums[self.k - 1]
        return -1
