"""
判断字符( [ { 是否 和 } ] )一一匹配
[{]}为无效
"""


def is_valid(self, chars):
    """
    使用栈进行存储字符，当为左字符则存入，为右字符则弹栈看是否匹配，
    最后需保证栈为空
    :param self:
    :param chars:
    :return:
    """
    stack = []
    map = {')': '(', ']': '[', '{': '}'}
    for c in chars:
        # 当为{ [ ( 时，入栈
        if c not in map:
            stack.append(c)
        # 通过map获取v不与出栈字符对应，出现异常字符
        elif not stack or map[c] != stack.pop():
            return False
    return not stack


"""
也可采用将字符串进行两两替换 {} () [] ,最后为”“方可，但是时间复杂度超过O(n)
"""
