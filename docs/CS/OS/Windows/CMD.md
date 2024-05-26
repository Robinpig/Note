## Introduction


```powershell
for /d %a in (*) do move "%a\*" . && rd /s /q "%a" 
```



