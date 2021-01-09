from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
import time
import HTMLTestRunner
import unittest

driver = webdriver.Firefox()
# print("set Browser 480 width,800 height ")
# de = driver.set_window_size(480, 800)
driver.implicitly_wait(5)

first_url = "https://www.baidu.com"
print("now access %s" % (first_url))
driver.get(first_url)

# # 进入搜索设置项
# link = driver.find_element_by_link_text("设置")
# ActionChains(driver).move_to_element(link).perform()
#
# driver.find_element_by_link_text("搜索设置").click()
# time.sleep(2)
#
# # #设置每页搜索结果为50条
# choice = driver.find_element_by_name("NR")
# choice.find_element_by_xpath("//option[@value='50']").click()
# time.sleep(2)
#
# # 保存设置
# driver.find_element_by_xpath("//a[@class='prefpanelgo']").click()
time.sleep(3)

# 弹框处理
# accept - 点击【确认】按钮
# dismiss - 点击【取消】按钮
# driver.switch_to_alert().accept()

# 跳转到百度首页后，进行搜索表
driver.find_element_by_id('kw').send_keys("selenium")
time.sleep(3)
driver.find_element_by_id('su').click()

time.sleep(10)
# 跳转到第二个url
second_url = "http://news.baidu.com"
driver.get(second_url)
driver.back()

print("return the first url ")
driver.forward()

time.sleep(3)
print("get html test runner")
# h = HtmlTestRunner.HTMLTestRunner(template='C:\\Users\\vito\\Desktop\\template')
#   生成测试报告文件

filename = 'C:\\Users\\vito\\Desktop\\selenium\\result.html'

fp = open(filename, 'wb')

runner = HTMLTestRunner.HTMLTestRunner(stream=fp)
# runner = unittest.TextTestRunner()
runner.run()
time.sleep(10)
fp.close()
driver.quit()
