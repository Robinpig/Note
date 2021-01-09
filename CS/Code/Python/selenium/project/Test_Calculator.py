import os, sys

current_dir = os.path.abspath(os.path.dirname(__file__))
sys.path.append(current_dir)



from calculator import Calculator


def test_add():
    c = Calculator(3, 4)
    result = c.__add__()
    assert result == 7, 'add fuction fail'


if __name__ == '__main__':
    test_add()
