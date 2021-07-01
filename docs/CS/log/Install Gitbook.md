


## install node 10.23.0

```shell
brew install node@10.23.0
```

or use npm re-install

```shell
n 10.23.0
```

check version

```shell
>npm -v
6.14.8

>node -v
v10.23.0
```



## install gitbook 2.3.0

```shell
npm install -g gitbook-cli@2.3.0
```

check version

```shell
>gitbook -V
CLI version: 2.3.0
GitBook version: 3.1.1
```

if the gitbook version is over 3.2.2

```shell
>cd ~/.gitbook/versions/3.2.2
>rm -rf node_modules
>rm -f package.json
>npm i
```



