import requests

target = "https://search.jd.com/Search?keyword=rtx2060super&enc=utf-8&pvid=4ffb068ce2064661b69118579176e7f5"
req = requests.get(url=target)
print(req.text)