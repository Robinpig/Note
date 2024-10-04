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

