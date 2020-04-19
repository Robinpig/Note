# coding:utf-8
import unittest
import time
import random

import HTMLTestRunner


class Test_Class(unittest.TestCase):

    def setUp(self):
        self.seq = list(range(10))

    def test_shuffle(self):
        # make sure the shuffled sequence does not lose any elements
        random.shuffle(self.seq)
        self.seq.sort()
        self.assertEqual(self.seq, list(range(10)))

        # should raise an exception for an immutable sequence
        print("test_shuffle")
        self.assertRaises(TypeError, random.shuffle, (1, 2, 3))

    def test_choice(self):
        element = random.choice(self.seq)
        print("test_choice")
        self.assertTrue(element in self.seq)

    def test_sample(self):
        with self.assertRaises(ValueError):
            random.sample(self.seq, 20)
        for element in random.sample(self.seq, 5):
            self.assertTrue(element in self.seq)

    def test_sun(self):
        self.temp = 5 + 6
        print("sun test")
        self.assertEqual(self.temp, 11)


if __name__ == "__main__":
    testsuite = unittest.TestSuite()

    #    添加测试用例到测试集中
    testsuite.addTest(Test_Class("test_shuffle"))
    testsuite.addTest(Test_Class("test_choice"))
    testsuite.addTest(Test_Class("test_sample"))
    testsuite.addTest(Test_Class("test_sun"))

    #   生成测试报告文件
    filename = 'C:/Users/vito/Desktop/selenium/result.html'
    fp = open(filename, 'wb')
    runner = HTMLTestRunner.HTMLTestRunner(stream=fp, title='测试结果', description='测试报告.')
    #    runner = unittest.TextTestRunner()
    runner.run(testsuite)
    fp.close()
    # unittest.main(testRunner=HTMLTestRunner.HTMLTestRunner(output = 'E:\\WorkItem\\TestItem\\testcase\\'))
