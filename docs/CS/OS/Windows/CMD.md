## Introduction


```powershell
for /d %a in (*) do move "%a\*" . && rd /s /q "%a" && del *.html
```

```powershell
mkdir mp3 && move *.mp3  mp3 & move *.m4a mp3
```


```powershell
(for /d %a in (*) do move "%a\*" . && rd /s /q "%a" && del *.html) & mkdir mp3 && move *.mp3  mp3 & move *.m4a mp3
```


```powershell

ren 
```


## Links


