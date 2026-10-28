## Introduction

Django 是一个「开箱即用（batteries included）」的 Python 全栈 Web 框架，与 [FastAPI](/docs/CS/Framework/FastAPI.md) 的「路由层很薄、契约绑在类型系统」形成鲜明对照：Django 把 ORM、admin 后台、认证、迁移、表单、模板都内置在同一套约定里。代价是组件之间耦合强——替换任一层（例如换掉它自带的模板引擎或 ORM）的成本都高。

Django 采用 **MVT（Model-View-Template）** 架构，这是经典 MVC 的 Django 式表述，选型的完整对照见 [Ecosystem](/docs/CS/Python/Ecosystem.md)。核心约定：

- **约定优于配置**：一个「app」该有哪些文件、settings 里 `INSTALLED_APPS` 如何登记，Django 都有固定结构。
- **DRY 与显式优于隐式**：复用靠模板继承、queryset 复用、CBV mixin，而不是复制粘贴。
- **不重复造轮子**：自带 ORM 而非让用户手写 SQL，自带 admin 而非每个项目写一套 CRUD。

## Version Baseline

| 系列 | 类型 | 发布 | Python 要求 | 支持终止 |
| :--- | :--- | :--- | :--- | :--- |
| 6.1 | 特性版 | 2026-08 | 3.12 – 3.14 | 主流 2027-04 / 扩展 2027-12 |
| **5.2 LTS** | 长期支持 | 2025-04 | 3.10 – 3.14 | 主流 2025-12 / 扩展 **2028-04** |
| 6.2 LTS | 长期支持（计划） | 2027-04 | — | 扩展 2030-04 |

版本基线：**生产保守选 5.2 LTS**（维护到 2028-04，矩阵最宽）；追新特性选 6.1。重要变更：Django 已通过 **DEP 20** 决定 **2028 年起改为年度发布**，届时每版都享受三年支持（取消单独的 LTS 标签），版本号改用年份（如 Django 2028）。本文代码锚定 5.2/6.x 通用写法。

## Project and App

Django 区分 **project（项目）** 与 **app（应用）**：project 是配置与装配层，app 是可插拔的功能模块（一个 project 可挂多个 app，一个 app 也可被多个 project 复用）。

```shell
django-admin startproject mysite   # 生成 project：settings.py / urls.py / asgi.py / wsgi.py / manage.py
python manage.py startapp blog     # 在 project 内生成 app：models.py / views.py / admin.py / migrations/
```

- `manage.py`：project 专属的命令行入口，所有管理命令都经它（见 [Management Commands](#management-commands)）。
- `settings.py`：整个 project 的配置中心（见 [Settings](#settings)）。
- `asgi.py` / `wsgi.py`：服务器装配入口（见 [WSGI and ASGI](#wsgi-and-asgi)）。
- `urls.py`：根路由（见 [URLconf](#urlconf)）。

## Settings

`settings.py` 是 Django 行为的唯一集中开关。最常用的几项：

| 配置 | 作用 |
| :--- | :--- |
| `INSTALLED_APPS` | 启用的 app 列表；自带 app（`django.contrib.admin/auth/sessions/contenttypes`）都在这里登记，自建 app 也要手动加 |
| `DATABASES` | 数据库连接（默认 `default`，支持多库 `using()`）；驱动走 `ENGINE`（`django.db.backends.postgresql` 等） |
| `MIDDLEWARE` | 中间件链，**顺序敏感**（见 [Middleware](#middleware)） |
| `TEMPLATES` | 模板引擎配置（DTL 默认 `DjangoTemplates`，`APP_DIRS=True` 会自动扫描各 app 的 `templates/`） |
| `STATIC_URL` / `STATIC_ROOT` | 静态资源 URL 与 `collectstatic` 收集目标目录（见 [Deployment](#deployment)） |
| `ALLOWED_HOSTS` | 生产 `DEBUG=False` 时必填的受信域名白名单 |
| `AUTH_USER_MODEL` | 自定义用户模型的开关（见 [Auth and Sessions](#auth-and-sessions)） |

## ORM and Migrations

Django 的 ORM 把数据库表映射为 Python 类，避免手写 SQL。模型定义在 `models.py`：

```py
from django.db import models

class Article(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    author = models.ForeignKey(
        "auth.User", on_delete=models.CASCADE, related_name="articles"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["-created_at"])]
```

要点：

- **QuerySet 是惰性的**：只有真正取值（迭代、`len()`、`list()`、切片或 `count()`）才会发 SQL，因此可以链式拼接 `.filter().exclude().select_related()` 而不产生多余查询。
- **关联字段**：`ForeignKey` / `ManyToManyField` / `OneToOneField`；反向访问靠 `related_name`。
- **管理器**：`Model.objects` 是默认 manager，可自定义 manager 封装复用查询。
- **迁移是版本化的 schema 变更**：

```shell
python manage.py makemigrations   # 比对 model 与已有迁移，生成新的迁移文件
python manage.py migrate          # 按依赖顺序把迁移应用到数据库
```

迁移系统自 1.7 起内置于框架（此前依赖第三方 South）。迁移文件落在各 app 的 `migrations/` 目录，是**可审查、可回滚**的 Python 代码，而非自动生成的一次性 SQL。

## URLconf

路由集中在 `urls.py`，用 `path()`（静态/转换器）与 `re_path()`（正则）声明：

```py
from django.urls import path
from . import views

urlpatterns = [
    path("articles/<int:pk>/", views.article_detail, name="article-detail"),
    path("articles/", views.article_list, name="article-list"),
]
```

- 内置转换器：`str` / `int` / `slug` / `uuid` / `path`（捕获含 `/` 的整段）。
- `include()` 把子路由挂到前缀下，实现 app 级路由解耦：

```py
path("blog/", include("blog.urls"))
```

`name=` 让模板与视图用 `reverse()` 反查 URL，避免硬编码路径。

## Views

视图接收 `HttpRequest`、返回 `HttpResponse`（或其子类 `JsonResponse` / `HttpResponseRedirect`）。两种写法：

**函数视图（FBV）**——直接、显式：

```py
from django.http import HttpResponse

def article_list(request):
    return HttpResponse("list")
```

**类视图（CBV）**——靠继承与 mixin 复用。`as_view()` 在 URLconf 里把类转成可调用视图，`dispatch()` 按 HTTP method 分发到 `get()` / `post()`：

```py
from django.views import View

class ArticleDetail(View):
    def get(self, request, pk):
        return HttpResponse(f"detail {pk}")
# urlconf 中写 path("...", ArticleDetail.as_view())
```

`django.views.generic` 还提供通用 CBV（`ListView` / `DetailView` / `CreateView` / `UpdateView` / `DeleteView`），把「查列表 / 查详情 / 增删改」这类 CRUD 样板收敛成配置。

## Templates

Django 模板语言（DTL）做表现层，强调**模板继承**而非 include 拼接：

```html
{% extends "base.html" %}
{% block content %}
  <h1>{{ article.title }}</h1>
  {% for a in articles %}<li>{{ a.title }}</li>{% endfor %}
{% endblock %}
```

- `{{ }}` 输出变量，`{% %}` 执行标签（循环 / 判断 / 继承），`|filter` 做格式化。
- 视图用 `render(request, "blog/article_list.html", {"articles": ...})` 注入 context。
- 自动 HTML 转义默认开启，防 XSS；渲染未受信内容时用 `|safe` 需谨慎。

## Forms

`django.forms` 统一处理「接收输入 → 校验 → 清洗 → 渲染」：

```py
from django import forms
from .models import Article

class ArticleForm(forms.ModelForm):
    class Meta:
        model = Article
        fields = ["title", "body"]
```

- `form.is_valid()` 触发校验，结果在 `form.cleaned_data`；`ModelForm` 可直接 `form.save()` 落库。
- 模板里放 `{% csrf_token %}` 防跨站请求伪造，CSRF 校验由中间件统一拦截。

## Admin

Django 最被称道的「开箱即用」特性：**自动 CRUD 后台**，无需为管理界面写代码：

```py
from django.contrib import admin
from .models import Article

@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ["title", "created_at"]   # 列表页展示字段
    list_filter = ["created_at"]
    search_fields = ["title"]
```

`ModelAdmin` 还能配 `fieldsets`（分组编辑）、`inlines`（内联编辑关联对象）、`raw_id_fields`（大表外键优化）等。注册即生效，访问 `/admin` 即可。

## Auth and Sessions

认证与授权是 `django.contrib.auth` 的内置能力：

- **可插拔用户模型**：默认 `User`（用户名 + 密码 + 邮箱）；自定义需设 `AUTH_USER_MODEL` 并从 `AbstractUser`（扩字段）或 `AbstractBaseUser`（完全自定义）继承。
- **密码存储**：默认 `PBKDF2` 加盐哈希；`argon2` / `bcrypt` 作为可选后端。明文密码永不落库。
- **权限与组**：每个模型自动拥有 add/change/delete 权限，可授予用户或组；`request.user` 在视图里直接拿到。
- **会话**：`django.contrib.sessions` 基于数据库/缓存的 session 中间件，配合 `login(request, user)` / `logout(request)` / `authenticate()`。

## Middleware

中间件是包裹视图的**处理链**，统一做认证、CSRF、会话、安全头、消息等横切逻辑。`MIDDLEWARE` 列表**顺序敏感**：请求自上而下穿过，响应自下而上返回。

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
```

自定义中间件实现 `process_request` / `process_view` / `process_exception` / `process_response` / `process_template_response` 钩子。

## WSGI and ASGI

Django 默认是**同步**框架，传统部署走 WSGI（`wsgi.py` 暴露 `application` 对象）。3.0 起引入 ASGI 支持（`asgi.py`），逐步补上异步能力：

- **3.1+** 支持 `async def` 异步视图；
- **4.1+** 提供异步 ORM（`await article.aget()`、`await obj.asave()`、异步迭代 QuerySet）。
- 同步视图里调用阻塞 I/O 会占住 worker 线程；异步视图里调用同步阻塞库需用 `sync_to_async` 包裹。异步原理见 [Asyncio](/docs/CS/Python/Asyncio.md)。

注意：Django 自带的 HTTP 服务器是**请求-响应模型**，连接在处理完即关闭，**原生不支持 WebSocket / 长连接**——这类需求要靠第三方 [Channels](https://github.com/django/channels)（基于 ASGI）另起一层。

## Management Commands

`manage.py` 是 Django 自带管理 CLI 的入口，常用内置命令：

| 命令 | 作用 |
| :--- | :--- |
| `runserver` | 开发服务器（自动重载，**仅开发用**） |
| `makemigrations` / `migrate` | 生成并应用数据库迁移 |
| `shell` | 带项目环境的 Python REPL（配 `django-extensions` 的 `shell_plus` 更佳） |
| `collectstatic` | 把各 app 静态文件收集到 `STATIC_ROOT` 供生产托管 |
| `check` | 静态检查配置与模型一致性 |
| `createsuperuser` | 创建 admin 超级用户 |
| `dumpdata` / `loaddata` | 导出 / 导入数据库 fixture |

业务还能在 `management/commands/` 下写自定义命令（如定时任务入口），被 `manage.py <name>` 直接调用。后台异步任务（如发邮件、视频转码）通常交给 Celery（见 [MQ](/docs/CS/MQ/MQ.md)），而非阻塞请求线程。

## Testing

Django 自带测试框架（基于 `unittest`）：

- `django.test.TestCase`：自动建测试库、事务回滚隔离，无需手动清数据。
- `django.test.Client`：模拟请求，断言响应内容/状态码，不依赖真实网络。
- 生产项目常用 `pytest` + `pytest-django`，复用同一套测试库与 settings。

## Deployment

生产部署与开发模式的差异集中在几条：

- **关闭 DEBUG**：`DEBUG=False` 必须配 `ALLOWED_HOSTS`，否则站点拒绝服务。
- **静态文件**：`collectstatic` 收集到 `STATIC_ROOT`，由 [Nginx](/docs/CS/CN/nginx/nginx.md) 直接托管（或 `whitenoise` 让 Django 自己发），**不要**让 Django 在 prod 提供静态文件。
- **WSGI 服务器**：用 Gunicorn / uWSGI 跑 `mysite.wsgi:application`，前面 Nginx 做 TLS、静态与反向代理（`proxy_pass http://127.0.0.1:8000`）。
- **数据库长连接**：`CONN_MAX_AGE` 复用连接，减少握手开销（连接池语义与 Java/HikariCP 不同，是 per-thread 复用）。
- **安全中间件**：`SECURE_SSL_REDIRECT`、`SESSION_COOKIE_SECURE`、`CSRF_COOKIE_SECURE`、`SECURE_HSTS_SECONDS` 等；`SECRET_KEY` 务必从环境变量注入，绝不入库。
- **Nginx 反代**后注意 `X-Forwarded-For` / `X-Forwarded-Proto`，否则 `request.is_secure()` 与客户端 IP 会失真。

## Django REST Framework

[Django REST Framework（DRF）](https://www.django-rest-framework.org/) 是构建 HTTP API 的**事实上标准**第三方库（非 Django 内置），填补了 Django 原生「无 API 层」的空白：

- **Serializer / ModelSerializer**：双向做「模型 ↔ JSON」的校验与序列化。
- **ViewSet + Router**：把「列表 / 详情 / 增删改」收敛成路由，自动生成端点。
- **Browsable API**：自带可交互的网页文档，调试友好。
- **认证与权限**：`TokenAuthentication` / `SessionAuthentication`、权限类（`IsAuthenticated` 等）与 Django 的 auth 体系衔接。

若只需轻量 JSON 接口、且契约以类型注解为主，[FastAPI](/docs/CS/Framework/FastAPI.md) 更省认知；若项目本就是 Django 全栈、再补一组 API，DRF 与既有 ORM / auth / admin 复用度最高。

## Links

- [Ecosystem](/docs/CS/Python/Ecosystem.md)
- [Typing](/docs/CS/Python/Typing.md)
- [Concurrency](/docs/CS/Python/Concurrency.md)
- [MQ](/docs/CS/MQ/MQ.md)
- [CS](/docs/CS/CS.md)

## References

- [Django documentation](https://docs.djangoproject.com/en/stable/)
- [Django 版本与支持周期](https://www.djangoproject.com/download/)
- [DEP 20 – Annual Release Cycle](https://www.djangoproject.com/weblog/2026/aug/10/annual-release-cycle/)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [Channels (ASGI for Django)](https://github.com/django/channels)
