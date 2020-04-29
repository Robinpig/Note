# all of classes and methods are objects
def ask(name):
    print(name)


class new:

    def __init__(self):
        print("xixixi")


my_function = ask
print(my_function("hahaha"))

my_class = new()
print(my_class)

print("type of object:")
print(type(object))
print("type of list:")
print(type(list))
print("type of type:")
print(type(type))
print("base class of object:")
print(object.__bases__)
print("base class of list:")
print(list.__bases__)
print("base class of type:")
print(type.__bases__)
# object是所有类的基类
# type是object的instance和子类
# list是type的实例
