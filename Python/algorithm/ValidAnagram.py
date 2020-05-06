"""
对两个字符串进行比较，判断其中字符是否全部相等，
顺序无关，字符数量和字符种类相同
art和tra
cat和atc
"""


def hash_anagram(str1, str2):
    """
    使用dictionary存储字符和字符数，
    三轮遍历，O(n)
    :param str1:
    :param str2:
    :return:
    """
    dic1, dic2 = {}, {}
    for item in str1:
        dic1[item] = dic1.get(item, 0) + 1
    for item in str2:
        dic2[item] = dic2.get(item, 0) + 1
    return dic1 == dic2


def sort_anagram(str1, str2):
    """
    将两个字符串按字符进行排序，再进行比较，
    通常quickSort O(n*log(n))
    :param str1:
    :param str2:
    :return:
    """
    return sorted(str1) == sorted(str2)


if __name__ == '__main__':
    str1 = "asdabfg"
    str2 = "gfdsaga"
    print(sort_anagram(str1, str2))
    print(hash_anagram(str1, str2))
