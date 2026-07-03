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



## PowerShell

从微软商店进行安装



设置默认配置文件

点击开始菜单，打开 终端 (Terminal)。
点击标题栏的 下拉箭头 (∨)，选择 设置。
选择 启动 - 默认配置文件，在下拉菜单中选择 PowerShell


设置系统默认终端应用（可选但推荐）

按 Win + I 打开系统 设置。
依次点击 隐私和安全性 -> 开发者选项（或在 Win11 较新版本中在 系统 -> 对于开发人员 中）。
找到 终端 选项，将其设置为 Windows 终端。
设置完成后，当你按 Win + X 并选择“终端”，或者在文件资源管理器中右键选择“在终端中打开”时，默认打开的就是 PowerShell 7 了



打开你设置好的默认命令行，输入以下命令并回车：

```powershell
$PSVersionTable
```

查看输出结果中的 PSVersion：
如果显示为 7.x.x，说明成功设置为了 PowerShell。
如果显示为 5.1.x，说明打开的还是 Windows PowerShell，请检查上述步骤中的路径或配置文件是否选错。






## Links

- [Windows](/docs/CS/OS/Windows/Windows.md)
