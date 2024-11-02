## Introduction




Storage

Hash Map



## Protocol



1. Local
2. SSH
3. HTTP
4. Git



git

Port 9418

## Command

### pull

```shell
git pull -a //
```


### delete
```shell
# delete remote branch 
git push origin --delete branchName
```

### branch
```shell
git branch

git branch -r 

git branch -a

# delete local branch
git branch -d branchName
```


### reset

代码回滚使用revert会增加一条commit记录



> [!WARNING]
>
> reset is dangerous

使用reset修改的是HEAD 需要强制push

```shell
git reset --hard [commit hash]

git push -f
```

其它开发需要同步HEAD, 之后再执行commit 同步前先确保本地代码stash

```shell
git reset --hard origin/master
```



## Sub

```shell
git submodule add https://github.com/user/repo.git sub-repo
```
- `git submodule init` 初始化子模块。
- `git submodule update` 更新子模块。


```shell
git subtree add –prefix=sub-repo https://github.com/user/repo.git master
```
update子树
```shell
git subtree pull –prefix=sub-repo https://github.com/user/repo.git master
```

## Hooks


CVE-2024-32002

## Links

