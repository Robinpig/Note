from selenium import webdriver

driver = webdriver.Firefox()
# driver = webdriver.Chrome()
# driver = webdriver.Ie()
driver.get("https://www.baidu.com")
driver.find_element_by_id("kw").send_keys("Selenium")
driver.find_element_by_id("su").click()
driver.find_element_by_name("wd")
driver.find_element_by_class_name("s_ipt")
driver.find_element_by_tag_name("input")
driver.find_element_by_link_text("hao123")
driver.find_element_by_partial_link_text("")


driver.quit()