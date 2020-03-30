from selenium import webdriver

driver = webdriver.Firefox()
print("set Browser 480 width,800 height ")
de = driver.set_window_size(480, 800)


first_url = "https://www.baidu.com"
print("no access %s" % (first_url))
driver.get(first_url)

second_url="http://news.baidu.com"
driver.get(second_url)
driver.back()

print("return ")
driver.forward()

driver.quit()
