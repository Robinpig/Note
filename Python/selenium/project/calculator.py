class Calculator:
    def __init__(self, a, b):
        self.a = int(a)
        self.b = int(b)

    def __add__(self):
        return self.a + self.b

    def __sub__(self):
        return self.a - self.b

    def __mul__(self):
        return self.a * self.b

    def __div__(self):
        return self.a / self.b
